import random
import sys
import requests
import os
import time
from openai import OpenAI
from typing import Optional
from mcp.server.fastmcp import FastMCP
from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam
try:
    from dotenv import load_dotenv
    has_dotenv = True
except ImportError:
    has_dotenv = False
    print("提示: 未安装dotenv库，无法从.env文件加载配置")
    print("可通过运行 'pip install python-dotenv' 安装")

# Ghidra服务器配置
DEFAULT_GHIDRA_SERVER = "http://127.0.0.1:8080/"
ghidra_server_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GHIDRA_SERVER

# 获取脚本所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))

def safe_get(endpoint: str, params: dict = None) -> list:
    """
    Perform a GET request with optional query parameters.
    """
    if params is None:
        params = {}

    url = f"{ghidra_server_url}/{endpoint}"

    try:
        response = requests.get(url, params=params, timeout=5)
        response.encoding = 'utf-8'
        if response.ok:
            return response.text.splitlines()
        else:
            return [f"Error {response.status_code}: {response.text.strip()}"]
    except Exception as e:
        return [f"Request failed: {str(e)}"]

def safe_post(endpoint: str, data: dict | str) -> str:
    try:
        if isinstance(data, dict):
            response = requests.post(f"{ghidra_server_url}/{endpoint}", data=data, timeout=5)
        else:
            response = requests.post(f"{ghidra_server_url}/{endpoint}", data=data.encode("utf-8"), timeout=5)
        response.encoding = 'utf-8'
        if response.ok:
            return response.text.strip()
        else:
            return f"Error {response.status_code}: {response.text.strip()}"
    except Exception as e:
        return f"Request failed: {str(e)}"

# 初始化MCP
mcp = FastMCP("ghidra-mcp")

@mcp.tool()
def search_functions_by_name(query: str, offset: int = 0, limit: int = 100) -> list:
    """
    根据给定的子字符串搜索符合条件的函数名
    """
    if not query:
        return ["Error: query string is required"]
    return safe_get("searchFunctions", {"query": query, "offset": offset, "limit": limit})

@mcp.tool()
def decompile_function(name: str) -> str:
    """
    根据指定的函数名对函数进行反编译，并返回反编译后的C语言代码
    """
    return safe_post("decompile", name)

@mcp.tool()
def rename_function(old_name: str, new_name: str) -> str:
    """
    将指定的函数从当前名称重命名为新的用户定义名称。
    """
    return safe_post("renameFunction", {"oldName": old_name, "newName": new_name})

# 进度条工具函数和预取函数列表
def print_progress(current: int, total: int, bar_len: int = 40) -> None:
    if total <= 0:
        return
    filled = int(bar_len * current / total)
    bar = '█' * filled + '-' * (bar_len - filled)
    percent = (current / total) * 100
    print(f"\r进度: |{bar}| {current}/{total} ({percent:.1f}%)", end='', flush=True)


def fetch_all_functions(pattern: str, batch_size: int) -> list:
    """分页获取所有匹配的函数名列表以便统计总量"""
    all_funcs = []
    offset = 0
    while True:
        batch = search_functions_by_name(pattern, offset=offset, limit=batch_size)
        if not batch or not isinstance(batch, list) or len(batch) == 0:
            break
        all_funcs.extend(batch)
        offset += batch_size
        # 略微休眠避免请求过快
        time.sleep(0.1)
    return all_funcs

def get_all_methods_count(timeout: float = 1.5) -> int:
    """获取全部方法数量：methods?offset=0&limit=999999 的行数"""
    try:
        url = f"{ghidra_server_url}/methods?offset=0&limit=999999"
        resp = requests.get(url, timeout=timeout)
        if not resp.ok:
            return 0
        lines = resp.text.splitlines() if resp.text else []
        return len(lines)
    except Exception:
        return 0

def analyze_function(decompiled_code: str, client, model_name: str) -> Optional[str]:
    """使用AI模型分析反编译代码并生成合适的函数名"""
    if not decompiled_code or len(decompiled_code.strip()) == 0:
        print("警告: 收到空的反编译代码")
        return None
        
    try:
        # 调用OpenAI API
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                ChatCompletionSystemMessageParam(
                    role="system",
                    content="你是一个代码分析专家。你的任务是分析C语言代码并生成一个恰当的函数名。规则：\n1. 必须使用英文\n2. 必须使用驼峰命名法\n3. 名称必须反映函数的主要功能\n4. 只返回函数名，不要包含任何其他文字\n5. 如果无法分析代码，返回None\n6. 函数名长度不要超过50个字符"
                ),
                ChatCompletionUserMessageParam(
                    role="user",
                    content=f"这是反编译的C代码，请分析并只返回一个合适的函数名：\n\n{decompiled_code}"
                )
            ],
            temperature=0.7,
            max_tokens=50
        )
        
        new_name = response.choices[0].message.content.strip()
        
        # 验证返回的函数名是否符合要求
        if not new_name or len(new_name) > 50 or ' ' in new_name or '\n' in new_name:
            print(f"警告: AI返回了无效的函数名: {new_name}")
            return None
            
        return new_name
        
    except Exception as e:
        print(f"AI API调用失败: {str(e)}")
        return None

def process_functions(config: dict, client, model_name: str, functions: list, on_log=None, on_progress=None, stop_event=None):
    """批量处理函数重命名（基于预取的函数列表，带进度/日志回调）"""
    consecutive_failures = 0  # 初始化连续失败计数器
    max_consecutive_failures = 10 # 最大连续失败次数

    total = len(functions)  # 注意：这里的 total 表示“需处理的函数量”
    processed = 0

    # 回调包装
    def emit_log(text: str):
        try:
            if on_log:
                on_log(text)
            else:
                print(text)
        except Exception:
            # 回调异常不应影响主流程
            print(text)

    def emit_progress(done: int, all_count: int):
        try:
            if on_progress:
                on_progress(done, all_count)
            else:
                print_progress(done, all_count)
        except Exception:
            print_progress(done, all_count)

    try:
        for func_name in functions:
            # 检查停止信号
            if stop_event is not None and hasattr(stop_event, 'is_set') and stop_event.is_set():
                emit_log("\n收到停止信号，提前结束处理。")
                break

            if not func_name or not func_name.strip():
                processed += 1
                emit_progress(processed, total)
                continue

            # 提取纯函数名（移除@后的地址信息）
            clean_func_name = func_name.split(" @ ")[0] if " @ " in func_name else func_name

            try:
                # 获取反编译代码
                decompiled = decompile_function(clean_func_name)
                if not decompiled:
                    emit_log(f"\n跳过 {func_name}: 无反编译结果")
                    processed += 1
                    emit_progress(processed, total)
                    continue

                # 检查是否是真正的错误（而不是反编译结果）
                if decompiled.startswith("Error") or decompiled.startswith("Request failed"):
                    emit_log(f"\n跳过 {func_name}: {decompiled}")
                    processed += 1
                    emit_progress(processed, total)
                    continue

                emit_log(f"\n正在分析函数: {func_name}")
                # 只显示函数签名和开头部分
                first_line = decompiled.split('\n')[0]
                emit_log(f"函数签名: {first_line}")

                # AI分析并重命名
                new_name = analyze_function(decompiled, client, model_name)
                if not new_name:
                    emit_log(f"跳过 {func_name}: AI分析失败或返回无效函数名")
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        emit_log(f"\n连续 {max_consecutive_failures} 次AI调用失败或返回无效名称。")
                        emit_log("请检查您的API密钥是否正确或网络连接是否正常。脚本将停止。")
                        break
                else:
                    consecutive_failures = 0 # AI调用成功，重置计数器
                    # 执行重命名
                    #使用search_functions_by_name先检查此函数名字是否已经存在 如果存在则加上后缀
                    if search_functions_by_name(new_name, limit=1):
                        new_name += "_" + str(random.randint(1000, 9999))

                    result = rename_function(clean_func_name, new_name)
                    if "Error" not in result:
                        emit_log(f"重命名成功: {func_name} -> {new_name}")
                        
                    else:
                        emit_log(f"重命名失败 {func_name}: {result}")
                    emit_log("----------------------------------------")
            except Exception as e:
                emit_log(f"处理函数 {func_name} 时出错: {str(e)}")

            # 添加延迟避免API限制
            time.sleep(config['delay'])

            processed += 1
            emit_progress(processed, total)

    except Exception as e:
        emit_log(f"批处理过程出错: {str(e)}")


def run_rename(api_key: str, api_base: str, model_name: str, function_pattern: str, batch_size: int, delay_seconds: float, on_log=None, on_progress=None, stop_event=None):
    """
    供GUI调用的入口：执行预取与批量处理，并通过回调输出日志与进度。
    进度分母 = 需处理的函数量（即匹配关键词的数量）。
    """
    # 配置OpenAI客户端
    client = OpenAI(
        api_key=api_key,
        base_url=api_base
    )

    config = {
        'function_pattern': function_pattern,
        'batch_size': batch_size,
        'delay': delay_seconds,
    }

    # 预取所有函数（需处理的函数量）
    functions = fetch_all_functions(config['function_pattern'], config['batch_size'])
    need_total = len(functions)

    # 同时统计总函数量
    all_methods_total = get_all_methods_count()

    if on_log:
        on_log("开始批量处理函数重命名...")
        on_log(f"配置信息:")
        on_log(f"- 总函数量: {all_methods_total}")
        on_log(f"- 需处理函数量: {need_total}")
        on_log(f"- 函数名模式: {config['function_pattern']}")
        on_log(f"- 批处理大小: {config['batch_size']}")
        on_log(f"- 处理延迟: {config['delay']}秒")
        on_log("-" * 50)

    if need_total == 0:
        if on_log:
            on_log("无可处理函数，退出。")
        if on_progress:
            on_progress(0, 0)
        return

    # 初始进度（运行前应为0）
    if on_progress:
        on_progress(0, need_total)

    process_functions(config, client, model_name, functions, on_log=on_log, on_progress=on_progress, stop_event=stop_event)

    if on_log:
        on_log("处理完成")
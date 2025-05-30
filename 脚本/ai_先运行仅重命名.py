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

def process_functions(config: dict, client, model_name: str):
    """批量处理函数重命名"""
    consecutive_failures = 0  # 初始化连续失败计数器
    max_consecutive_failures = 10 # 最大连续失败次数

    try:
        offset = 0
        while True:
            # 获取一批函数
            functions = search_functions_by_name(config['function_pattern'], offset=offset, limit=config['batch_size'])
            if not functions or not isinstance(functions, list) or len(functions) == 0:
                break

            print(f"正在处理第 {offset + 1} 到 {offset + len(functions)} 个函数...")

            for func_name in functions:
                if not func_name or not func_name.strip():
                    continue

                # 提取纯函数名（移除@后的地址信息）
                clean_func_name = func_name.split(" @ ")[0] if " @ " in func_name else func_name

                try:
                    # 获取反编译代码
                    decompiled = decompile_function(clean_func_name)
                    if not decompiled:
                        print(f"跳过 {func_name}: 无反编译结果")
                        continue

                    # 检查是否是真正的错误（而不是反编译结果）
                    if decompiled.startswith("Error") or decompiled.startswith("Request failed"):
                        print(f"跳过 {func_name}: {decompiled}")
                        continue

                    print(f"\n正在分析函数: {func_name}")
                    # 只显示函数签名和开头部分
                    first_line = decompiled.split('\n')[0]
                    print(f"函数签名: {first_line}")
                    print("----------------------------------------")

                    # AI分析并重命名
                    new_name = analyze_function(decompiled, client, model_name)
                    if not new_name:
                        print(f"跳过 {func_name}: AI分析失败或返回无效函数名")
                        consecutive_failures += 1
                        if consecutive_failures >= max_consecutive_failures:
                            print(f"\n连续 {max_consecutive_failures} 次AI调用失败或返回无效名称。")
                            print("请检查您的API密钥是否正确或网络连接是否正常。脚本将停止。")
                            sys.exit(1) # 退出脚本
                        continue
                    else:
                        consecutive_failures = 0 # AI调用成功，重置计数器

                    # 执行重命名
                    #使用search_functions_by_name先检查此函数名字是否已经存在 如果存在则加上后缀
                    if search_functions_by_name(new_name, limit=1):
                        new_name += "_" + str(random.randint(1000, 9999))

                    result = rename_function(clean_func_name, new_name)
                    if "Error" not in result:
                        print(f"重命名成功: {func_name} -> {new_name}")
                    else:
                        print(f"重命名失败 {func_name}: {result}")

                except Exception as e:
                    print(f"处理函数 {func_name} 时出错: {str(e)}")

                # 添加延迟避免API限制
                time.sleep(config['delay'])

            offset += config['batch_size']

    except Exception as e:
        print(f"批处理过程出错: {str(e)}")

def main():
    # 尝试加载.env文件
    if has_dotenv:
        # 获取脚本所在目录的.env文件
        env_path = os.path.join(script_dir, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
            print(f"已从 {env_path} 加载环境变量配置")
        else:
            print("未找到.env文件，将使用默认配置")
    
    # OpenAI配置 - 优先从环境变量读取，如不存在则使用默认值
    openai_api_key = os.environ.get("OPENAI_API_KEY", "SK-XXXXXXXXXXXXXXXXXXXXXXXXXXX")
    openai_api_base = os.environ.get("OPENAI_API_BASE", "https://api.siliconflow.cn/")
    model_name = os.environ.get("OPENAI_MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
    
    print(f"使用模型: {model_name}")
    
    # 配置OpenAI客户端
    client = OpenAI(
        api_key=openai_api_key,
        base_url=openai_api_base
    )
    # 函数特征配置
    config = {
        'function_pattern': "FUN_",  # 要搜索的函数名模式
        'batch_size': 50,           # 每批处理的函数数量
        'delay': 1.0,              # 处理每个函数之间的延迟时间（秒）
    }
    print("开始批量处理函数重命名...")
    print(f"配置信息:")
    print(f"- 函数名模式: {config['function_pattern']}")
    print(f"- 批处理大小: {config['batch_size']}")
    print(f"- 处理延迟: {config['delay']}秒")
    print("-" * 50)
    
    process_functions(config, client, model_name)
    print("处理完成")

if __name__ == "__main__":
    main()

import sys
import requests
import os
import datetime
import concurrent.futures
from threading import Lock

# Ghidra服务器配置
DEFAULT_GHIDRA_SERVER = "http://127.0.0.1:8080/"
ghidra_server_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GHIDRA_SERVER

# 创建基于时间的输出目录
OUTPUT_DIR = os.path.join(os.getcwd(), f"项目_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 用于同步文件操作的锁
file_lock = Lock()
# 用于同步打印的锁
print_lock = Lock()

def safe_print(*args, **kwargs):
    """线程安全的打印函数"""
    with print_lock:
        print(*args, **kwargs)

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

def decompile_function(name: str) -> str:
    """
    Decompile a specific function by name and return the decompiled C code.
    """
    return safe_post("decompile", name)

def list_methods(offset: int = 0, limit: int = 100) -> list:
    """
    List all function names in the program with pagination.
    """
    return safe_get("methods", {"offset": offset, "limit": limit})

def get_unique_filename(directory: str, base_name: str, extension: str = '.txt') -> str:
    """生成唯一的文件名，如果文件已存在则添加序号"""
    with file_lock:
        counter = 1
        file_name = f"{base_name}{extension}"
        full_path = os.path.join(directory, file_name)
        
        while os.path.exists(full_path):
            file_name = f"{base_name}_{counter}{extension}"
            full_path = os.path.join(directory, file_name)
            counter += 1
        
        return file_name

def process_single_function(func_name: str) -> None:
    """处理单个函数的反编译和保存"""
    if not func_name or not func_name.strip():
        return

    # 提取纯函数名（移除@后的地址信息）
    clean_func_name = func_name.split(" @ ")[0] if " @ " in func_name else func_name

    try:
        # 获取反编译代码
        decompiled = decompile_function(clean_func_name)
        if not decompiled or "Error" in decompiled:
            safe_print(f"跳过 {func_name}: 反编译失败 - {decompiled if decompiled else '无反编译结果'}")
            return

        safe_print(f"\n正在处理函数: {func_name}")

        # 保存反编译代码到文件，使用唯一文件名
        unique_filename = get_unique_filename(OUTPUT_DIR, clean_func_name)
        save_path = os.path.join(OUTPUT_DIR, unique_filename)
        try:
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(f"// 函数名: {func_name}\n")
                f.write(f"// 保存时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(decompiled)
            safe_print(f"已保存源码到: {save_path}")
        except Exception as e:
            safe_print(f"保存源码失败: {str(e)}")

    except Exception as e:
        safe_print(f"处理函数 {func_name} 时出错: {str(e)}")

def save_functions(batch_size: int = 50, max_workers: int = 10):
    """使用多线程保存所有函数的反编译代码
    
    Args:
        batch_size: 每批处理的函数数量
        max_workers: 最大线程数
    """
    try:
        offset = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            while True:
                # 获取一批函数
                functions = list_methods(offset=offset, limit=batch_size)
                
                if not functions or len(functions) == 0:
                    safe_print("没有更多函数可处理")
                    break

                safe_print(f"正在处理第 {offset + 1} 到 {offset + len(functions)} 个函数...")

                # 提交所有任务到线程池
                futures = [executor.submit(process_single_function, func_name) for func_name in functions]
                
                # 等待所有任务完成
                concurrent.futures.wait(futures)

                offset += batch_size

    except Exception as e:
        safe_print(f"批处理过程出错: {str(e)}")

def main():
    # 获取命令行参数
    max_workers = 10  # 默认线程数
    if len(sys.argv) > 2:
        try:
            max_workers = int(sys.argv[2])
        except ValueError:
            safe_print("线程数必须是整数，使用默认值10")

    safe_print(f"开始保存所有函数的反编译代码")
    safe_print(f"源码将保存至目录: {OUTPUT_DIR}")
    safe_print(f"使用 {max_workers} 个线程并行处理")
    save_functions(max_workers=max_workers)
    safe_print("处理完成")

if __name__ == "__main__":
    main() 
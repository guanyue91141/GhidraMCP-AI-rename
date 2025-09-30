# 1. 读取 pip list 的输出
import subprocess
result = subprocess.run(['pip', 'list'], capture_output=True, text=True)
output = result.stdout

# 2. 解析输出，提取包名
packages_to_uninstall = []
lines = output.splitlines()
for line in lines[2:]:  # 跳过前两行 (分割线)
    if not line.strip():   # 跳过空行
        continue
    package_name = line.split(' ')[0]  # 获取包名 (假设包名是第一个单词)
    packages_to_uninstall.append(package_name)

# 3.  删除要保留的软件包
packages_to_keep = ['mcp', 'openai', 'argparse','pip']
for package in packages_to_keep:
    try:
        packages_to_uninstall.remove(package) # 移除指定的包
    except ValueError: # 如果指定的包不在列表中，忽略
        pass

# 4. 生成卸载命令
uninstall_commands = [f'pip uninstall -y {package}' for package in packages_to_uninstall]

# 5. 打印卸载命令 (或者执行它们，见下一步)
print("以下是将会执行的卸载命令：")
for cmd in uninstall_commands:
    print(cmd)

# 6. **（可选，小心使用！）执行卸载命令**
#  取消注释下面的代码来真正执行卸载。
#  **务必在取消注释之前仔细检查上面打印的命令！**
for cmd in uninstall_commands:
    subprocess.run(cmd, shell=True)

print("已生成卸载命令。请检查命令并取消注释代码来执行卸载。")


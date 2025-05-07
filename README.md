# Ghidra
## 基于GhidraMcp的快速部署脚本
### 项目要求：python>3.10


### Ghidra下载：https://github.com/NationalSecurityAgency/ghidra
### JDK21+下载：https://www.oracle.com/java/technologies/javase/jdk21-archive-downloads.html
### GhidraMCP配置：
https://github.com/user-attachments/assets/75f0c176-6da1-48dc-ad96-c182eb4648c3


# 使用说明
填入自己的硅基流动密钥，然后运行[ai_先运行仅重命名.py](%E8%84%9A%E6%9C%AC/ai_%E5%85%88%E8%BF%90%E8%A1%8C%E4%BB%85%E9%87%8D%E5%91%BD%E5%90%8D.py)
等待所有的FUN_xxxx函数重命名结束后，再运行[ai_再运行文件保存.py](%E8%84%9A%E6%9C%AC/ai_%E5%86%8D%E8%BF%90%E8%A1%8C%E6%96%87%E4%BB%B6%E4%BF%9D%E5%AD%98.py)
然后配置樱桃或者cursor的MCP进行分析即可。

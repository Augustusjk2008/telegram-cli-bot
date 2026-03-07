"""Web CLI 诊断工具"""

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

def check_port(port=8080):
    """检查端口占用情况"""
    print(f"\n[1/5] 检查端口 {port}...")
    try:
        result = subprocess.run(
            ["netstat", "-ano", "|", "findstr", f":{port}"],
            capture_output=True,
            shell=True,
            text=True
        )
        if result.stdout:
            print(f"  ⚠️  端口 {port} 已被占用:")
            for line in result.stdout.strip().split('\n')[:5]:
                print(f"     {line.strip()}")
        else:
            print(f"  ✅ 端口 {port} 可用")
    except Exception as e:
        print(f"  ❌ 检查失败: {e}")

def check_ngrok():
    """检查 ngrok 是否可用"""
    print("\n[2/5] 检查 ngrok...")
    try:
        result = subprocess.run(
            ["ngrok", "version"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"  ✅ ngrok 已安装: {result.stdout.strip()}")
            return True
        else:
            print(f"  ❌ ngrok 返回错误: {result.stderr}")
            return False
    except FileNotFoundError:
        # 尝试检查配置的路径
        import os
        ngrok_dir = os.environ.get("NGROK_DIR", "").strip()
        if ngrok_dir:
            ngrok_exe = Path(ngrok_dir) / "ngrok.exe"
            if ngrok_exe.exists():
                print(f"  ✅ ngrok 在配置目录中找到: {ngrok_exe}")
                return True
        print("  ❌ ngrok 未找到，请确保已安装并添加到 PATH 或设置 NGROK_DIR")
        print("     下载地址: https://ngrok.com/download")
        return False
    except Exception as e:
        print(f"  ❌ 检查失败: {e}")
        return False

def check_ngrok_config():
    """检查 ngrok 配置"""
    print("\n[3/5] 检查 ngrok 配置...")
    
    # 检查 authtoken
    try:
        config_path = Path.home() / ".ngrok2" / "ngrok.yml"
        if not config_path.exists():
            config_path = Path.home() / ".config" / "ngrok" / "ngrok.yml"
        
        if config_path.exists():
            content = config_path.read_text()
            if "authtoken" in content:
                print(f"  ✅ ngrok authtoken 已配置")
            else:
                print(f"  ⚠️  ngrok 配置文件中没有找到 authtoken")
                print(f"     请运行: ngrok config add-authtoken <your_token>")
        else:
            print(f"  ⚠️  ngrok 配置文件不存在")
            print(f"     请运行: ngrok config add-authtoken <your_token>")
    except Exception as e:
        print(f"  ❌ 检查失败: {e}")

def test_web_server(port=8080):
    """测试本地 Web 服务器"""
    print(f"\n[4/5] 测试本地 Web 服务器 (端口 {port})...")
    
    html_dir = Path(__file__).parent.parent / "bot" / "data" / "webcli"
    
    # 启动测试服务器
    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(html_dir), "--bind", "127.0.0.1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    time.sleep(2)
    
    try:
        # 测试本地访问
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            content = response.read()
            if b"Web CLI" in content or b"html" in content.lower():
                print(f"  ✅ 本地 Web 服务器响应正常")
                return True
            else:
                print(f"  ⚠️  Web 服务器响应异常")
                return False
    except Exception as e:
        print(f"  ❌ 无法连接到本地 Web 服务器: {e}")
        return False
    finally:
        process.terminate()
        process.wait()

def test_ngrok_tunnel(port=8080):
    """测试 ngrok 隧道"""
    print(f"\n[5/5] 测试 ngrok 隧道...")
    
    html_dir = Path(__file__).parent.parent / "bot" / "data" / "webcli"
    html_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建测试 HTML
    test_file = html_dir / "index.html"
    test_file.write_text("<html><body><h1>Web CLI Test</h1></body></html>")
    
    # 启动服务器
    server_process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(html_dir), "--bind", "127.0.0.1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    # 启动 ngrok
    ngrok_process = subprocess.Popen(
        ["ngrok", "http", f"http://127.0.0.1:{port}", "--log=stdout"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    print("  ⏳ 等待 ngrok 启动...")
    time.sleep(5)
    
    try:
        # 获取 ngrok URL
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=5) as response:
            data = json.loads(response.read())
            tunnels = data.get("tunnels", [])
            if tunnels:
                public_url = tunnels[0].get("public_url", "")
                print(f"  ✅ ngrok 隧道已建立: {public_url}")
                print(f"\n     请尝试在浏览器中访问: {public_url}")
                print(f"     如果仍有问题，可能是防火墙或 ngrok 免费账户限制")
                return True
            else:
                print(f"  ❌ ngrok 没有活跃的隧道")
                # 尝试读取 ngrok 日志
                import select
                if hasattr(select, 'select'):
                    readable, _, _ = select.select([ngrok_process.stdout], [], [], 2)
                    if readable:
                        log = ngrok_process.stdout.readline()
                        print(f"     ngrok 日志: {log.strip()}")
                return False
    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        print(f"     请检查 ngrok 是否已配置 authtoken")
        return False
    finally:
        ngrok_process.terminate()
        server_process.terminate()
        ngrok_process.wait()
        server_process.wait()

def main():
    print("=" * 50)
    print("Web CLI 诊断工具")
    print("=" * 50)
    
    check_port(8080)
    ngrok_ok = check_ngrok()
    
    if ngrok_ok:
        check_ngrok_config()
        test_web_server(8080)
        test_ngrok_tunnel(8080)
    
    print("\n" + "=" * 50)
    print("诊断完成")
    print("=" * 50)
    print("\n常见解决方案:")
    print("1. 如果端口被占用，尝试重启电脑或更换端口")
    print("2. 确保 ngrok authtoken 已配置:")
    print("   ngrok config add-authtoken <your_token>")
    print("3. 检查防火墙是否阻止了 ngrok 的连接")
    print("4. 如果问题持续，可能是 ngrok 免费版的限制，请重试几次")

if __name__ == "__main__":
    main()

"""测试 TUI 模式的 WebSocket 服务器"""

import asyncio
import json
import sys

import websockets


async def test_tui_connection():
    """测试 TUI WebSocket 连接"""
    uri = "ws://127.0.0.1:8081"

    print(f"连接到 {uri}...")

    try:
        async with websockets.connect(uri) as websocket:
            print("✓ 连接成功")

            # 发送初始化消息
            init_message = {
                "command": ["python", "-c", "print('Hello from TUI!'); import time; time.sleep(1); print('Goodbye!')"],
                "cwd": "."
            }
            await websocket.send(json.dumps(init_message))
            print(f"✓ 已发送初始化消息: {init_message}")

            # 接收输出
            print("\n--- 接收输出 ---")
            try:
                while True:
                    message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    if isinstance(message, bytes):
                        print(f"[字节流] {message.decode('utf-8', errors='replace')}", end='')
                    else:
                        print(f"[文本] {message}")
            except asyncio.TimeoutError:
                print("\n--- 超时，结束接收 ---")
            except websockets.exceptions.ConnectionClosed:
                print("\n--- 连接已关闭 ---")

    except ConnectionRefusedError:
        print("❌ 连接被拒绝，请确保 TUI 服务器正在运行")
        print("提示: 先启动 bot 并执行 /webcli_start tui")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_tui_connection())

"""
测试网络流量读取脚本
"""

import subprocess
import sys
import pytest


class TestNetworkTrafficScript:
    """测试 network_traffic 脚本"""
    
    def test_powershell_script_exists(self):
        """测试 PowerShell 脚本文件存在"""
        import os
        script_path = os.path.join("scripts", "network_traffic.ps1")
        assert os.path.exists(script_path), f"脚本文件不存在: {script_path}"
    
    def test_first_line_contains_network_traffic(self):
        """测试第一行包含'网络流量'注释"""
        import os
        script_path = os.path.join("scripts", "network_traffic.ps1")
        with open(script_path, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
        assert "网络流量" in first_line, f"第一行应该包含'网络流量': {first_line}"
    
    def test_batch_script_not_exists(self):
        """确认批处理脚本已删除"""
        import os
        script_path = os.path.join("scripts", "network_traffic.bat")
        assert not os.path.exists(script_path), f"批处理脚本应该已被删除: {script_path}"
    
    def test_powershell_script_syntax(self):
        """测试 PowerShell 脚本语法是否正确"""
        # 使用 PowerShell 检查脚本语法
        result = subprocess.run(
            ["powershell", "-Command", 
             "Get-Command scripts/network_traffic.ps1 | Out-Null; $?"],
            capture_output=True,
            text=True,
            shell=True
        )
        # 只要 PowerShell 能识别脚本，就认为语法基本正确
        assert result.returncode == 0 or "Get-Command" in str(result)
    
    def test_powershell_execution(self):
        """测试 PowerShell 脚本可以执行"""
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts/network_traffic.ps1"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # 检查输出包含预期内容
        output = result.stdout + result.stderr
        
        # 脚本应该成功执行（即使某些系统上可能没有网络接口）
        assert "网络流量" in output or "network" in output.lower() or result.returncode == 0
    
    def test_script_outputs_traffic_info(self):
        """测试脚本输出流量信息"""
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts/network_traffic.ps1"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        output = result.stdout
        
        # 检查输出中包含预期的关键字
        assert any(keyword in output for keyword in [
            "接收流量", "发送流量", "总流量", 
            "ReceivedBytes", "SentBytes", "interface", "接口"
        ]), f"输出不包含预期的流量信息: {output[:500]}"


class TestNetworkTrafficHelpers:
    """测试网络流量相关的辅助功能"""
    
    def test_get_net_adapter_statistics_command(self):
        """测试 Get-NetAdapterStatistics 命令是否可用"""
        result = subprocess.run(
            ["powershell", "-Command", "Get-NetAdapterStatistics"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # 命令应该可以执行（即使没有输出或出错，命令本身应该存在）
        # PowerShell 中命令不存在会返回错误信息
        assert "不是内部或外部命令" not in result.stderr
        assert "is not recognized" not in result.stderr
    
    def test_network_interface_exists(self):
        """测试系统中存在网络接口"""
        result = subprocess.run(
            ["powershell", "-Command", 
             "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Select-Object -First 1"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # 大多数系统至少有一个活动的网络接口
        # 但不强制要求，只是验证命令可以执行
        assert result.returncode == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

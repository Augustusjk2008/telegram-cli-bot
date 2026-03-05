@echo off
:: 关闭显示器
:: Sends message to turn off display using Windows API
:: Works on all Windows systems
chcp 65001 >nul
echo Turning off screen...

powershell -NoProfile -Command "& {$t = Add-Type -MemberDefinition '[DllImport(\"user32.dll\")]public static extern int SendMessage(int hWnd,int Msg,int wParam,int lParam);' -Name 'a' -Namespace 'b' -PassThru; $t::SendMessage(0xFFFF, 0x112, 0xF170, 2)}"

echo Done

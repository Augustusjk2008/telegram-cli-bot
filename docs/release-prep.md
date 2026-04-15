## 历史清理

如果远端仓库已经公开过旧内容，发布 1.0 前先清理历史并强推：

~~~bash
git filter-repo --path .env --path managed_bots.json --path .web_tunnel_state.json --path .cloudflared_url --invert-paths --force
git push origin --force --all
git push origin --force --tags
~~~

## 发布前校验

~~~bash
python -m pytest tests/test_install_scripts.py tests/test_start_scripts.py tests/test_updater.py tests/test_web_api.py tests/test_release_assets.py -q
cd front && npm test -- src/test/settings-screen.test.tsx src/test/real-client.test.ts
cd front && npm run build
~~~

## 发布说明建议

- Windows 包含 `install.bat` / `install.ps1` / `start.bat` / `start.ps1`
- Linux 包含 `install.sh` / `start.sh`
- 自动更新通过 GitHub Releases 分发，下载后在下次启动时应用
- 不要把真实 `.env`、`managed_bots.json`、`.web_admin_settings.json`、`.session_store.json` 打进发布包

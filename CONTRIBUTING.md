# Contributing to Orbit Safe Claw

Thank you for contributing. Please use GitHub Issues to discuss substantial
changes before opening a pull request, and keep each pull request focused on a
single concern.

## Contribution terms

Unless you explicitly state otherwise in writing, any contribution you
intentionally submit for inclusion in this project is provided under the
Apache License, Version 2.0, in accordance with Section 5 of that license. By
submitting a contribution, you confirm that you have the right to provide it
under those terms.

Do not submit code, media, data, or other material that you are not authorized
to contribute. Identify third-party material and its license in the pull
request, and update `THIRD_PARTY_NOTICES.md` when the distributed product gains
a dependency or bundled asset that requires attribution.

The contribution license does not grant rights to use the Orbit Safe Claw
project marks. See `TRADEMARKS.md` for the brand policy.

## Development checks

Follow `AGENTS.md` and the repository's testing guidance. At minimum, run the
checks relevant to the changed area and include the actual results in the pull
request:

```bash
# Backend
python -m pytest tests -q

# Frontend
cd front
npm run test:gate
npm run lint
npm run build
```

Never commit credentials, real `.env` values, runtime `managed_bots.json`, or
user data from `~/.tcb/`.

---

# 参与贡献

感谢参与 Orbit Safe Claw。较大的改动请先通过 GitHub Issues 沟通，并让每个 Pull Request 聚焦于一个主题。

除非你在提交时以书面方式明确声明其他条款，否则你有意提交并纳入本项目的贡献，将依照 Apache License 2.0 第 5 节按同一许可证提供。提交贡献即表示你确认自己有权按这些条款提供相关内容。

请勿提交无权授权的代码、媒体、数据或其他材料。Pull Request 中应标明第三方材料及其许可证；如果发布产品新增了需要署名的依赖或随附资产，请同步更新 `THIRD_PARTY_NOTICES.md`。项目标识的使用不属于贡献许可范围，具体见 `TRADEMARKS.md`。

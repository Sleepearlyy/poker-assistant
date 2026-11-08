# 求解器说明

`solver/poker-engine.exe` 是本地编译的 GTO 计算引擎，二进制随项目提供，不需要联网，也不需要 Rust 工具链。

- 上游：https://github.com/b-inary/postflop-solver
- 固定提交：`9d1509fe5077d019825f833eed04b16d342dfda1`
- 许可证：AGPL-3.0-or-later（见 `vendor/postflop-solver/LICENSE`）
- 本仓库中的外壳 `src/main.rs`：把 JSON 请求转成牌局，调用上游库求解，输出每个动作的 EV、频率和可利用度。

## 自己重新编译（可选）

需要 Rust stable + MinGW-w64。构建产物在本机已用 `x86_64-pc-windows-gnu` 测试：

```powershell
cd solver
cargo build --release --offline
copy target\release\poker-engine.exe poker-engine.exe
```

## 协议

进程从 stdin 读一个 JSON，向 stdout 写一个 JSON；失败时退出码为 2，并输出 `{"error": "..."}`。`advisor.py` 通过子进程调用它。

请求支持：

- `mode`: `gto` 或 `equity`
- `hero`: 两张牌，如 `["Ah","As"]`
- `board`: 0、3、4、5 张公牌
- `ranges`: 范围字符串数组（`gto` 需要 2 个，`equity` 支持 1~8 个），如 `["QQ+,AKs"]`
- `pot`、`stack`、`call`、`hero_ip`（`gto`）
- `bet_sizes` / `raise_sizes`（可选，默认 `50%` / `2.5x`；树超过 512 MiB 时自动退化为加注全下）

EV 口径：以当前决策为起点、弃牌为 0、单位为筹码。

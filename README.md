# 德扑助手

Windows 本地牌桌识别工具，适配 Poker Fate 当前布局和四色牌。

**[下载安装包](https://github.com/Sleepearlyy/poker-screen-reader/releases/latest)**，安装后从开始菜单打开。支持 Windows 10/11 x64，无需 Python 或 CUDA。

- 左下角置顶，按 **A** 识别一次，**Q** 收起；也可点击按钮。
- 读取各座位筹码、下注、底池、大小盲、手牌和公牌，显示动作建议与 EV。
- 截图和计算均在本机完成，不自动下注。

多人局使用**蒙特卡洛＋简化对手模型，并非完整 GTO**；符合条件的单挑转牌/河牌使用 CFR。EV 以当前决定为起点、弃牌为 0，不含抽水或 ICM。遮挡、识别误差和范围假设会影响结果，尚未接入 Pluribus 模型。

设置与记录保存在 `%LOCALAPPDATA%\PokerScreenReader`。安装程序未商业签名。

## 开发

Python 3.10/3.11、Rust stable 和 C++ 构建工具：

```powershell
pip install -r requirements-build.txt
cd solver
cargo build --release --locked
Copy-Item target/release/poker-engine.exe poker-engine.exe
cd ..
python popup.py
python -m unittest discover -v
```

打包需 Inno Setup 6：`python scripts/build_release.py --iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"`。
布局配置见 `layouts.json`；GitHub Actions 可自动构建安装包。

## 许可

[AGPL-3.0-or-later](LICENSE)。第三方声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。与游戏官方无隶属关系。

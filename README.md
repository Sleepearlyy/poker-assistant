# 德扑助手 · Poker Screen Reader

Windows 桌面上的本地牌桌识别工具：左下角置顶，按一次 **A** 识别一次，按 **Q** 收起结果。读取筹码、下注、底池、大小盲、自己的手牌及公共牌，并显示推荐动作和各动作的筹码 EV。

**多人局的建议采用简化模型，不是完整 GTO。** 仅符合条件的单挑转牌/河牌使用本地 CFR 求解。未接入 Pluribus 训练模型。

## 下载与运行

到 [Releases](https://github.com/Sleepearlyy/poker-screen-reader/releases) 下载 Windows x64 版本：

- `*-setup.exe`：安装后从开始菜单启动，可选择创建桌面快捷方式，无需管理员权限。
- `*-portable.zip`：解压整个文件夹，双击 `德扑助手.exe`；不要单独移动 exe 或删除 `_internal`。

无需安装 Python、Conda、CUDA 或显卡驱动。系统要求 Windows 10/11 x64。

安装包未进行商业代码签名，Windows 可能显示“未知发布者”。可以核对同一发布页的 SHA256SUMS.txt，或按下面的步骤从源码构建。

## 使用

1. 打开 Poker Fate，保持完整牌桌可见。当前只适配这一游戏的既有布局和四色牌主题。
2. 启动助手，自动寻找游戏客户区；也可在助手中框选完整游戏区域。
3. 轮到自己行动后按 **A**，或点击“识别”。助手暂时隐藏自身后截图，随后显示牌面、各座位后手与下注、建议和 EV。
4. 点击“计算依据”查看对手范围与计算假设。游戏变化后再次按 A；Q 收起面板。

空座保留原位置；识别不到的金额可能为未知值。游戏中的 K/M 缩写只提供近似筹码数。下注面板、动画或其他窗口遮挡会影响读取。

程序不点击游戏或自动下注。A/Q 仅在游戏或助手位于前台且未检测到文本输入时触发；其他输入方式仍可能影响热键判断，可用按钮代替。

## 建议和 EV 从哪里来

**通常情况：蒙特卡洛模拟 + 对手反应模型。** 按位置和可见动作设定对手范围，每种范围组合模拟约 1500～3000 次。对候选下注假设对手弃牌、跟注或再加注，随后直接摊牌，比较估算 EV。不完整模拟后续街博弈、复杂边池、抽水或锦标赛 ICM。

**单挑转牌/河牌：Discounted CFR。** 使用 [b-inary/postflop-solver](https://github.com/b-inary/postflop-solver)，仅在只剩一名对手、公牌至少四张、双方后手可读、非只能全下/弃牌且跟注成本小于底池时尝试求解。双方范围假设为较强的前 45% 起手牌；下注和加注尺度有限。结果只适用于这些假设和动作树；未收敛会标注，失败回退到估算模型。

EV 以当前决策为起点、弃牌为 0，单位为筹码；已投入的筹码视为沉没成本。界面“胜率”指模型中的摊牌权益，包含平局分成，不是最终盈利概率。筹码 EV 和以大盲为单位的 EV 分开显示。

单张截图不能还原完整行动历史，也不能知道对手真实范围。识别错误或假设不符时，建议与 EV 可能不准确。

## 数据与隐私

截图识别和计算都在本机完成，应用不上传画面或联网查询建议。

- 安装版及便携版设置、识别结果、错误日志：`%LOCALAPPDATA%\PokerScreenReader`。
- 源码运行时：项目内的 `popup-settings.json` 和 `results/`。
- 开源仓库与发布包不包含私人截图、玩家记录、服务器访问配置或训练模型。

不想保存旧记录时，可关闭程序后删除上述用户数据目录；卸载程序默认保留该目录。

## 从源码运行

安装 Python 3.11 x64 和 Rust stable（Windows MSVC 工具链及 Visual Studio C++ Build Tools）。在仓库根目录运行：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cd solver
cargo build --release --locked
Copy-Item target\release\poker-engine.exe poker-engine.exe
cd ..
python popup.py
```

也支持 MinGW-w64 / `x86_64-pc-windows-gnu`。上游求解器源码已固定在 `solver/vendor/`，Cargo.lock 固定 Rust 依赖。

命令行读取自己的截图：

```powershell
python reader.py image C:\path\table.png --output results\latest.json
python popup.py --sample C:\path\table.png
python popup.py --diagnostics results\diagnostics.json
python -m unittest discover -v
```

`layouts.json` 使用相对坐标 `[x1,y1,x2,y2]`。布局大幅变化时需重新校准，例如 `python reader.py calibrate C:\path\table.png pot`。未公开的私人截图回归测试会跳过，核心规则和引擎测试不依赖这些截图。

## 构建安装包

安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)，构建原生引擎后运行：

```powershell
python -m pip install -r requirements-build.txt
python scripts/build_release.py --iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

`release/` 生成便携 zip、安装 exe、对应源码 zip 及 SHA-256。每个软件包也附带对应源码。GitHub Actions 支持手动构建；推送与 app_info.py 版本一致的 `v*` 标签可自动发布。

## 许可证

[AGPL-3.0-or-later](LICENSE)。第三方组件及许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 `solver/NOTICE.md`。项目与 Poker Fate 官方无隶属关系。

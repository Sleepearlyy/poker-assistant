# 第三方组件

应用源码采用 AGPL-3.0-or-later，完整许可证见 LICENSE。发布包包含同版本的完整应用源码和构建脚本。

- `solver/vendor/postflop-solver`：b-inary/postflop-solver，提交 `9d1509fe5077d019825f833eed04b16d342dfda1`，AGPL-3.0-or-later；保留上游源码、版权与 LICENSE。详见 solver/NOTICE.md。
- RapidOCR / rapidocr-onnxruntime：Apache-2.0；ONNX Runtime：MIT；OpenCV：Apache-2.0；MSS：MIT；NumPy：BSD-3-Clause。
- Python、Tcl/Tk、PyInstaller 及其他传递依赖：保留所安装发行包中的许可证；PyInstaller 使用其引导器分发例外。
- `licenses/` 由打包脚本从实际安装的依赖中收集许可证与元数据；以这些文件的具体条款为准。
- 不分发私人游戏截图、玩家资料、识别记录或服务器训练模型。程序不属于游戏官方软件。

依赖不会因为应用采用 AGPL 而改变其原有许可证。向他人分发修改后的版本时，应提供与二进制对应的完整源码及构建说明。

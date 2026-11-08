# 原生引擎

外壳 `src/main.rs` 通过 stdin/stdout JSON 调用 vendored postflop-solver。
上游：https://github.com/b-inary/postflop-solver
固定提交：9d1509fe5077d019825f833eed04b16d342dfda1
许可证：AGPL-3.0-or-later，见 vendor/postflop-solver/LICENSE。

`cargo build --release --locked` 后，将 target/release/poker-engine.exe 复制到本目录。

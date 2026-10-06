# -*- coding: utf-8 -*-
"""run.bat 端到端测试。

为什么需要这个文件:
run.bat 曾因**换行符是 LF**(cmd.exe 要求 CRLF)而完全无法运行, 报出
"'0' 不是内部或外部命令" —— 单看脚本内容没有任何问题, 只有实跑
才能发现。同理还有两个隐性缺陷:
  - ``if %errorlevel%==0``: 括号块内 %var% 在解析期一次性展开
  - 不加 ``call`` 调用 .bat: 会替换当前批处理上下文而不返回,
    PATH 里存在 python.bat 时脚本静默停在标题行

因此本脚本用替身解释器 + 最小 PATH 逐一验证各分支与退出码。
不需要 PySide6, 仅标准库, 跨平台可跑。

用法:
    python tests/test_runbat.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNBAT = os.path.join(ROOT, "run.bat")

IS_WIN = sys.platform == "win32"


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


class TestRunBat(unittest.TestCase):
    """run.bat 的静态契约与实跑行为。"""

    @classmethod
    def setUpClass(cls):
        if not IS_WIN:
            raise unittest.SkipTest("仅 Windows 适用")
        if not os.path.exists(RUNBAT):
            raise unittest.SkipTest("run.bat 不存在")
        cls.raw = _read_bytes(RUNBAT)
        cls.text = cls.raw.decode("utf-8")
        cls.sandbox = tempfile.mkdtemp(prefix="runbat_")
        # 隔离目录内也要有一份, 供实跑
        shutil.copy(RUNBAT, os.path.join(cls.sandbox, "run.bat"))
        shutil.copy(os.path.join(ROOT, "requirements.txt"),
                    os.path.join(cls.sandbox, "requirements.txt"))
        with open(os.path.join(cls.sandbox, "app.py"), "w",
                  encoding="utf-8") as f:
            f.write("# stub\n")
        cls.sys32 = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"),
                                 "System32")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.sandbox, ignore_errors=True)

    # ---------- 静态契约 ----------

    def test_line_endings_are_crlf(self):
        """回归: 换行符必须是 CRLF。

        cmd.exe 按 CRLF 切分命令, 遇 LF 会把多行错误拼接 —— 表现为
        "'0' 不是内部或外部命令" 这类莫名其妙的报错。
        """
        lf = self.raw.count(b"\n")
        crlf = self.raw.count(b"\r\n")
        self.assertGreater(lf, 0)
        self.assertEqual(
            lf, crlf,
            f"存在裸 LF({lf - crlf} 个)。cmd.exe 需要 CRLF, "
            f"请用 newline='\\r\\n' 写该文件")

    def test_no_gitattributes_violation(self):
        """仓库应显式约束 .bat 用 CRLF, 避免 checkout 后再坏。"""
        ga = os.path.join(ROOT, ".gitattributes")
        self.assertTrue(os.path.exists(ga), "缺少 .gitattributes")
        with open(ga, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("*.bat", content)
        self.assertIn("crlf", content)

    def test_no_expandable_var_inside_if_block(self):
        """回归: 括号块内 %var% 在解析期一次性展开。

        原写法 ``if %errorlevel%==0 (...)`` 会拿到上一条命令的旧值,
        判断结果不可预期。
        """
        body = self.text
        self.assertNotIn("%errorlevel%==", body,
                         "不得在 if 条件中直接展开 %errorlevel%")

    def test_all_interpreter_calls_use_call(self):
        """回归: 调用 .bat 必须加 call。

        cmd 调用 .bat 若不加 call, 会用目标批处理替换当前上下文,
        执行完不再返回 —— 脚本会静默停在中间, 退出码却是 0。
        """
        for line in self.text.splitlines():
            code = line.strip()
            if code.startswith("%PY% ") or code.startswith("python ") \
                    or code.startswith("py -3 ") or code.startswith("py "):
                self.assertTrue(
                    code.startswith("call "),
                    f"解释器调用缺少 call 前缀: {code}")

    def test_checks_pyside6_dependency(self):
        """PySide6 是界面必需依赖, 缺失须被拦截并提示。"""
        self.assertIn("import PySide6", self.text,
                      "需探测 PySide6 是否已安装")
        self.assertIn("requirements.txt", self.text,
                      "需能自动安装缺失依赖")

    def test_propagates_exit_code(self):
        """需传递真实退出码, 不吞掉错误。"""
        self.assertIn("exit /b %RC%", self.text)

    # ---------- 实跑行为 ----------

    def _stub(self, tag, has_pyside, pip_ok, app_rc):
        """造 python.bat 替身。has_pyside/pip_ok/app_rc 控制分支。

        用 ``%~2`` 而非 ``%2``: 后者自带引号, ``if "%2"=="x"`` 会
        双重包裹导致比较恒不成立。
        """
        d = os.path.join(self.sandbox, tag)
        os.makedirs(d, exist_ok=True)
        lines = [
            "@echo off",
            'if "%~2"=="import sys" exit /b 0',
            f'if "%~2"=="import PySide6" exit /b '
            f'{0 if has_pyside else 1}',
            'if "%~1"=="--version" (echo Python 3.11.9 & exit /b 0)',
        ]
        if pip_ok:
            lines.append('if "%~1"=="-m" (echo [FAKEPIP] installing '
                         '& exit /b 0)')
        else:
            lines.append('if "%~1"=="-m" exit /b 1')
        lines += ["echo [FAKEAPP] running", f"exit /b {app_rc}"]
        path = os.path.join(d, "python.bat")
        with open(path, "w", encoding="ascii", newline="") as f:
            f.write("\n".join(lines).replace("\n", "\r\n"))
        return d

    def _run(self, path_dirs):
        env = {
            "SystemRoot": os.environ["SystemRoot"],
            "TEMP": self.sandbox,
            "ComSpec": os.path.join(self.sys32, "cmd.exe"),
            # 最小 PATH: 真实 Python 会被优先命中, 替身永远不生效
            "PATH": os.pathsep.join(list(path_dirs) + [self.sys32]),
        }
        r = subprocess.run(
            [os.path.join(self.sys32, "cmd.exe"), "/c", "run.bat"],
            cwd=self.sandbox, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
            stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def _assert_branch(self, dirs, expect_text, expect_rc):
        rc, out = self._run(dirs)
        self.assertIn(expect_text, out,
                      f"输出缺少 {expect_text!r}\n实际:\n{out[:500]}")
        self.assertEqual(rc, expect_rc,
                         f"退出码应为 {expect_rc}, 实际 {rc}\n{out[:300]}")

    def test_branch_no_python(self):
        empty = os.path.join(self.sandbox, "empty")
        os.makedirs(empty, exist_ok=True)
        self._assert_branch([empty], "未找到可用的 Python 3", 1)

    def test_branch_autoinstall_dependency(self):
        self._assert_branch(
            [self._stub("inst", False, True, 0)],
            "[FAKEPIP] installing", 0)

    def test_branch_install_failed(self):
        self._assert_branch(
            [self._stub("fail", False, False, 0)],
            "PySide6 安装失败", 1)

    def test_branch_app_crashed(self):
        self._assert_branch(
            [self._stub("crash", False, True, 3)],
            "程序异常退出, 退出码 3", 3)

    def test_branch_normal_exit(self):
        self._assert_branch(
            [self._stub("ok", False, True, 0)], "已正常退出", 0)

    def test_bat_python_does_not_silently_stop(self):
        """回归: PATH 中的 python.bat 不得让脚本静默停在标题行。

        未加 call 时, cmd 用 python.bat 替换当前批处理上下文, 执行完
        不返回 —— 只输出标题、退出码 0, 后续逻辑全不执行。
        """
        d = self._stub("silent", False, True, 0)
        rc, out = self._run([d])
        self.assertIn("[FAKEPIP] installing", out,
                      "脚本在调用 python.bat 后静默终止(call 缺失)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
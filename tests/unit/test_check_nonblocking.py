import pathlib
import subprocess
import sys
import tempfile
import unittest


CHECKER = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "check_nonblocking.py"


class NonblockingFixtures(unittest.TestCase):
    """Exercise the command against source fixtures, without compiling C++."""

    def setUp(self):
        self.assertTrue(CHECKER.is_file(), "nonblocking checker is not implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "src").mkdir()

    def write(self, path, source):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")

    def check(self, explicit_root=True):
        return subprocess.run(
            [sys.executable, "-B", str(CHECKER)] + ([str(self.root)] if explicit_root else []),
            cwd=self.root, capture_output=True, text=True, check=False,
        )

    def assert_rejected(self, path, line, result=None):
        result = self.check() if result is None else result
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"{path}:{line}:", result.stderr)

    def test_absent_future_runtime_is_reported_as_not_applicable(self):
        self.write("src/main.cpp", "int main() { return 0; }\n")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run_freerun", result.stdout)
        self.assertIn("not applicable", result.stdout)

    def test_default_root_is_current_working_directory(self):
        self.write("src/main.cpp", "int main() { return 0; }\n")
        self.assertEqual(self.check(explicit_root=False).returncode, 0)

    def test_missing_source_directory_cannot_pass(self):
        (self.root / "src").rmdir()
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("src", result.stderr)

    def test_every_receive_primitive_outside_net_cpp_is_rejected(self):
        for name in ("recvmmsg", "recvmsg", "recvfrom", "recv"):
            with self.subTest(name=name):
                self.write("src/other.cpp", f"void f() {{\n    ::{name}(fd, p, n, MSG_DONTWAIT);\n}}\n")
                self.assert_rejected("src/other.cpp", 2)

    def test_header_and_nested_source_receives_are_checked(self):
        self.write("src/detail/socket.hpp", "inline int f() { return recv(fd, p, n, MSG_DONTWAIT); }\n")
        self.assert_rejected("src/detail/socket.hpp", 1)

    def test_similar_filename_does_not_gain_net_exception(self):
        self.write("src/detail/net.cpp", "int f() { return recv(fd, p, n, MSG_DONTWAIT); }\n")
        self.assert_rejected("src/detail/net.cpp", 1)

    def test_fixed_flags_for_each_receive_primitive_pass(self):
        self.write("src/net.cpp", """namespace net {
int batch() { return ::recvmmsg(fd, msgs, 8, kHotRecvFlags, nullptr); }
int message() { return ::recvmsg(fd, msg, MSG_DONTWAIT); }
int source() { return ::recvfrom(fd, buf, len, kHotRecvFlags, addr, addrlen); }
int one() { return ::recv(fd, buf, len, MSG_DONTWAIT); }
}
""")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_multiline_receive_checks_the_flags_argument(self):
        self.write("src/net.cpp", """namespace net {
int batch() {
    return ::recvmmsg(
        fd, msgs, 8,
        kHotRecvFlags,
        nullptr);
}
}
""")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_zero_or_caller_flags_are_rejected(self):
        for flags in ("0", "flags", "kHotRecvFlagsExtra"):
            with self.subTest(flags=flags):
                self.write("src/net.cpp", f"int f() {{\n    return recv(fd, buf, len, {flags});\n}}\n")
                self.assert_rejected("src/net.cpp", 2)

    def test_unrelated_fixed_flag_token_cannot_approve_receive(self):
        self.write("src/net.cpp", "int f() { return recv(fd, kHotRecvFlags, len, 0); }\n")
        self.assert_rejected("src/net.cpp", 1)

    def test_comment_or_string_cannot_supply_fixed_flags(self):
        for suffix in ("/* MSG_DONTWAIT */", '// kHotRecvFlags', 'const char* s = "MSG_DONTWAIT";'):
            with self.subTest(suffix=suffix):
                self.write("src/net.cpp", f"int f() {{\n    recv(fd, p, n, 0); {suffix}\n}}\n")
                self.assert_rejected("src/net.cpp", 2)

    def test_namespace_and_qualified_blocking_helper_are_allowed(self):
        sources = (
            "namespace net {\nint recv_blocking(int fd) noexcept { return recvfrom(fd, p, n, 0, a, l); }\n}\n",
            "int net::recv_blocking(int fd) noexcept { return ::recv(fd, p, n, 0); }\n",
        )
        for source in sources:
            with self.subTest(source=source):
                self.write("src/net.cpp", source)
                result = self.check()
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_other_namespaces_and_similar_helpers_are_not_allowlisted(self):
        sources = (
            "namespace other { int recv_blocking(int fd) { return recv(fd,p,n,0); } }\n",
            "namespace net { int recv_blocking_extra(int fd) { return recv(fd,p,n,0); } }\n",
            "namespace net { namespace detail { int recv_blocking(int fd) { return recv(fd,p,n,0); } } }\n",
            "namespace net::detail { int recv_blocking(int fd) { return recv(fd,p,n,0); } }\n",
            "namespace net { class Other { int recv_blocking(int fd) { return recv(fd,p,n,0); } }; }\n",
        )
        for source in sources:
            with self.subTest(source=source):
                self.write("src/net.cpp", source)
                self.assert_rejected("src/net.cpp", 1)

    def test_blocking_allowlist_ends_at_function_closing_brace(self):
        self.write("src/net.cpp", """namespace net {
int recv_blocking(int fd) {
    if (fd >= 0) { return recv(fd, p, n, 0); }
    return -1;
}
int ordinary(int fd) {
    return recv(fd, p, n, 0);
}
}
""")
        self.assert_rejected("src/net.cpp", 7)

    def test_comments_and_literals_do_not_create_calls_or_braces(self):
        self.write("src/main.cpp", r'''// recv(fd, p, n, 0); {
/* recvfrom(fd, p, n, 0, a, l); } */
const char* a = "recvmsg(fd, p, 0); \" }";
const char* b = R"tag(recvmmsg(fd, p, n, 0, 0); " {)tag";
const char c = '}';
int run_freerun() {
    const char* s = "poll(fd); }";
    return 0;
}
''')
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("not applicable", result.stdout)

    def test_each_named_blocking_operation_in_freerun_is_rejected(self):
        for operation in ("net::recv_blocking(fd)", "poll(p, 1, 0)", "select(0, p, p, p, p)",
                          "epoll_wait(fd, p, 1, 0)", "sleep(1)", "std::this_thread::sleep_for(dt)",
                          "setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, p, n)"):
            with self.subTest(operation=operation):
                self.write("src/freerun.cpp", f"int run_freerun() {{\n    {operation};\n}}\n")
                self.assert_rejected("src/freerun.cpp", 2)

    def test_multiline_freerun_signature_and_nested_body_are_checked(self):
        self.write("src/freerun.cpp", """int run_freerun(
    const Config& cfg,
    int fd
) noexcept {
    if (fd >= 0) {
        net::recv_blocking
            (fd);
    }
}
""")
        self.assert_rejected("src/freerun.cpp", 6)

    def test_freerun_prototype_does_not_hide_later_definition(self):
        self.write("src/freerun.cpp", "int run_freerun(int);\nint run_freerun(int fd) { poll(p, 1, 0); }\n")
        self.assert_rejected("src/freerun.cpp", 2)

    def test_adjacent_origin_wait_is_outside_freerun_body(self):
        self.write("src/freerun.cpp", """int run_freerun() {
    if (ready) { net::recv_batch(fd, batch); }
    clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, p, nullptr);
    return 0;
}
int origin_wait() { return net::recv_blocking(fd); }
""")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("not applicable", result.stdout)

    def test_neighboring_calls_are_not_folded_into_a_safe_receive(self):
        self.write("src/net.cpp", "int f() { recv(fd,p,n,0); recv(fd,p,n,MSG_DONTWAIT); }\n")
        self.assert_rejected("src/net.cpp", 1)

    def test_reports_all_violations_in_source_order(self):
        self.write("src/other.cpp", "void f() {\n    recv(fd,p,n,0);\n    recvmsg(fd,p,0);\n}\n")
        result = self.check()
        self.assert_rejected("src/other.cpp", 2, result)
        self.assertIn("src/other.cpp:3:", result.stderr)
        self.assertLess(result.stderr.index("src/other.cpp:2:"), result.stderr.index("src/other.cpp:3:"))


if __name__ == "__main__":
    unittest.main()

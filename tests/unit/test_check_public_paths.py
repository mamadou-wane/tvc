import pathlib, subprocess, sys, tempfile, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import check_public_paths as cpp

# The violation this checker exists to remove, copied from docs/plan.md as it
# read at 2a937cd. Kept verbatim so a later refactor cannot stop detecting it.
PLAN_MD = """# Engineering plan

The governing document is the spec
(superpowers/specs/2026-08-14-tvc-restructure-design.md). This file is the
working summary of what ships when.
"""


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


class Fixture(unittest.TestCase):
    """Each case builds its own git repository, so no fixture tracks the real tree."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        write(self.root, ".gitignore", "docs/superpowers/\nSECRET.md\n")
        write(self.root, "docs/methodology.md", "# Methodology\n")
        write(self.root, "docs/superpowers/specs/2026-08-14-tvc-restructure-design.md",
              "# ignored spec\n")
        write(self.root, "SECRET.md", "# ignored\n")

    def tearDown(self):
        self.tmp.cleanup()

    def check(self):
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        return cpp.violations(str(self.root))


class Accepts(Fixture):
    def test_link_to_a_tracked_file(self):
        write(self.root, "README.md", "See [methodology](docs/methodology.md).\n")
        self.assertEqual(self.check(), [])

    def test_bare_prose_mention_of_a_tracked_file(self):
        write(self.root, "README.md", "The rules live in docs/methodology.md today.\n")
        self.assertEqual(self.check(), [])

    def test_tracked_path_inside_a_code_fence(self):
        write(self.root, "README.md", "```\ncat docs/methodology.md\n```\n")
        self.assertEqual(self.check(), [])

    def test_a_token_with_no_md_ending_is_out_of_scope(self):
        # docs/results.md:289 cites an internal log by number, which no
        # document-shaped rule reaches. That citation is edited by hand.
        write(self.root, "README.md", "the check ai-log 0030 asked for\n")
        self.assertEqual(self.check(), [])


class Rejects(Fixture):
    def test_the_docs_plan_line_4_violation(self):
        write(self.root, "docs/plan.md", PLAN_MD)
        bad = self.check()
        self.assertEqual(len(bad), 1)
        path, lineno, token, hit = bad[0]
        self.assertEqual((path, lineno), ("docs/plan.md", 4))
        self.assertEqual(token, "superpowers/specs/2026-08-14-tvc-restructure-design.md")
        self.assertEqual(hit, "docs/superpowers/specs/2026-08-14-tvc-restructure-design.md")

    def test_the_same_token_inside_a_code_fence(self):
        write(self.root, "docs/plan.md",
              "# Plan\n\n```\nsuperpowers/specs/2026-08-14-tvc-restructure-design.md\n```\n")
        bad = self.check()
        self.assertEqual([(p, n) for p, n, _, _ in bad], [("docs/plan.md", 4)])

    def test_a_link_target_resolved_through_the_docs_retry(self):
        write(self.root, "README.md",
              "[spec](superpowers/specs/2026-08-14-tvc-restructure-design.md)\n")
        bad = self.check()
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0][3],
                         "docs/superpowers/specs/2026-08-14-tvc-restructure-design.md")

    def test_an_ignored_file_at_the_repository_root(self):
        write(self.root, "README.md", "Read SECRET.md first.\n")
        bad = self.check()
        self.assertEqual([(p, n, t) for p, n, t, _ in bad],
                         [("README.md", 1, "SECRET.md")])


if __name__ == "__main__":
    unittest.main()

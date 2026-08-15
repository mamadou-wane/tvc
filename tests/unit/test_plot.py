import sys, pathlib, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import plot_jitter

class ReadCdf(unittest.TestCase):
    def test_reads_and_drops_p1(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("Value,Percentile,TotalCount,1/(1-Percentile)\n")
            f.write("10.0,0.5,100,2.0\n10.0,1.0,200,inf\n")
            path = f.name
        xs, ys = plot_jitter.read_cdf(path)
        self.assertEqual(xs, [10.0])
        self.assertEqual(ys, [0.5])

class YFloor(unittest.TestCase):
    def test_y_floor_from_counts(self):
        self.assertAlmostEqual(plot_jitter.y_floor([300_000]), 0.5 / 300_000)
        self.assertEqual(plot_jitter.y_floor([]), 5e-6)

class SeriesLabel(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(plot_jitter.series_label("L3.jitter.csv"), "L3")

    def test_repeat(self):
        self.assertEqual(plot_jitter.series_label("L3.r2.jitter.csv"), "L3.r2")

    def test_naive(self):
        self.assertEqual(plot_jitter.series_label("L3.jitter_naive.csv"), "L3")

    def test_naive_repeat(self):
        self.assertEqual(plot_jitter.series_label("L3.r2.jitter_naive.csv"), "L3.r2")

if __name__ == "__main__":
    unittest.main()

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DocsTest(unittest.TestCase):
    def test_every_api_route_is_documented(self):
        with open(os.path.join(ROOT, "pianotrack", "server.py")) as f:
            server = f.read()
        with open(os.path.join(ROOT, "README.md")) as f:
            readme = f.read()
        routes = set(re.findall(r'path == "(/api/[a-z.]+)"', server))
        routes |= {"/api/sessions/<id>/events", "/api/sessions/<id>.mid"}
        missing = [r for r in sorted(routes) if r not in readme]
        self.assertEqual(missing, [], "document these routes in README.md")

    def test_readme_images_exist(self):
        with open(os.path.join(ROOT, "README.md")) as f:
            readme = f.read()
        for path in re.findall(r'(docs/[\w-]+\.png)', readme):
            self.assertTrue(os.path.exists(os.path.join(ROOT, path)), path)


if __name__ == "__main__":
    unittest.main()

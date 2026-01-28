import unittest

from pywire.runtime.page import BasePage
from pywire.runtime.router import Route, Router, URLHelper, URLTemplate


class MockPage(BasePage):
    pass


class TestRouterExhaustive(unittest.TestCase):
    def test_route_compilation_params(self) -> None:
        # Test root path
        r0 = Route("/", MockPage, "root")
        self.assertTrue(r0.regex.match("/"))
        self.assertFalse(r0.regex.match("/test"))

        # Test :param syntax
        r1 = Route("/test/:id", MockPage, "r1")
        self.assertTrue(r1.regex.match("/test/123"))
        self.assertFalse(r1.regex.match("/test/123/more"))

        # Test {param} syntax
        r2 = Route("/users/{name}", MockPage, "r2")
        self.assertTrue(r2.regex.match("/users/alice"))

        # Test types
        r3 = Route("/projects/:id:int", MockPage, "r3")
        self.assertTrue(r3.regex.match("/projects/123"))
        self.assertFalse(r3.regex.match("/projects/abc"))

        r4 = Route("/files/{path:str}", MockPage, "r4")
        self.assertTrue(r4.regex.match("/files/somefile.txt"))

        # Test default type
        r5 = Route("/custom/:val:unknown", MockPage, "r5")
        self.assertTrue(r5.regex.match("/custom/foo"))

    def test_route_match_params(self) -> None:
        r = Route("/user/:id:int/:action", MockPage, "user_action")
        params = r.match("/user/42/edit")
        self.assertEqual(params, {"id": "42", "action": "edit"})

        self.assertIsNone(r.match("/user/abc/edit"))

    def test_url_template_format(self) -> None:
        t1 = URLTemplate("/user/:id/edit")
        self.assertEqual(t1.format(id="123"), "/user/123/edit")

        t2 = URLTemplate("/projects/{pid:int}/{action}")
        self.assertEqual(t2.format(pid=42, action="view"), "/projects/42/view")

        # Test __str__ normalization
        self.assertEqual(str(t1), "/user/{id}/edit")
        self.assertEqual(str(t2), "/projects/{pid}/{action}")

    def test_url_helper(self) -> None:
        routes = {"home": "/", "user": "/user/:id"}
        helper = URLHelper(routes)

        url = helper["user"].format(id=1)
        self.assertEqual(url, "/user/1")

        with self.assertRaises(KeyError):
            helper["missing"]

        # Test __str__ of helper
        h_str = str(helper)
        self.assertIn("'home': '/'", h_str)
        self.assertIn("'user': '/user/{id}'", h_str)

    def test_router_basics(self) -> None:
        router = Router()

        class PageA(MockPage):
            __route__ = "/a"

        class PageB(MockPage):
            __routes__ = {"list": "/b", "detail": "/b/:id"}

        router.add_page(PageA)
        router.add_page(PageB)

        self.assertEqual(len(router.routes), 3)

        # Match A
        match = router.match("/a")
        assert match is not None
        self.assertEqual(match[0], PageA)
        self.assertEqual(match[2], None)

        # Match B List
        match = router.match("/b")
        assert match is not None
        self.assertEqual(match[0], PageB)
        self.assertEqual(match[2], "list")

        # Match B Detail
        match = router.match("/b/123")
        assert match is not None
        self.assertEqual(match[0], PageB)
        self.assertEqual(match[1], {"id": "123"})
        self.assertEqual(match[2], "detail")

        # Match None
        self.assertIsNone(router.match("/c"))

    def test_remove_routes_for_file(self) -> None:
        router = Router()

        class PageF(MockPage):
            __route__ = "/f"
            __file_path__ = "/path/to/f.pywire"

        router.add_page(PageF)
        self.assertEqual(len(router.routes), 1)

        router.remove_routes_for_file("/path/to/f.pywire")
        self.assertEqual(len(router.routes), 0)


if __name__ == "__main__":
    unittest.main()

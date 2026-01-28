import unittest

from pywire.runtime.page import BasePage
from pywire.runtime.router import Route, Router, URLHelper, URLTemplate


class MockPage(BasePage):
    pass


class TestRouterRuntime(unittest.TestCase):
    def test_route_compilation_simple(self) -> None:
        route = Route("/test", MockPage, "test")
        self.assertIsNotNone(route.regex.match("/test"))
        self.assertIsNone(route.regex.match("/test/other"))

    def test_route_compilation_params(self) -> None:
        # Test :param syntax
        route1 = Route("/user/:id", MockPage, "user")
        match1 = route1.regex.match("/user/123")
        assert match1 is not None
        self.assertEqual(match1.group("id"), "123")

        # Test {param} syntax
        route2 = Route("/post/{slug}", MockPage, "post")
        match2 = route2.regex.match("/post/hello-world")
        assert match2 is not None
        self.assertEqual(match2.group("slug"), "hello-world")

    def test_route_compilation_types(self) -> None:
        # Test :int type
        route = Route("/user/:id:int", MockPage, "user")
        self.assertIsNotNone(route.regex.match("/user/123"))
        self.assertIsNone(route.regex.match("/user/abc"))

        # Test {param:int} type
        route2 = Route("/post/{id:int}", MockPage, "post")
        self.assertIsNotNone(route2.regex.match("/post/456"))
        self.assertIsNone(route2.regex.match("/post/xyz"))

    def test_route_match_params(self) -> None:
        route = Route("/user/:id/posts/:post_id", MockPage, "user_post")
        params = route.match("/user/1/posts/2")
        self.assertEqual(params, {"id": "1", "post_id": "2"})

    def test_url_template_format(self) -> None:
        tpl = URLTemplate("/user/:id/posts/:post_id")
        url = tpl.format(id=1, post_id=10)
        self.assertEqual(url, "/user/1/posts/10")

        tpl2 = URLTemplate("/page/{slug}")
        self.assertEqual(tpl2.format(slug="contact"), "/page/contact")

    def test_url_helper(self) -> None:
        helper = URLHelper({"home": "/", "user": "/user/:id"})
        self.assertEqual(str(helper["home"]), "/")
        self.assertEqual(helper["user"].format(id=5), "/user/5")

        with self.assertRaises(KeyError):
            _ = helper["missing"]

    def test_router_add_page_with_routes(self) -> None:
        class PageWithRoutes(MockPage):
            __routes__ = {"main": "/main", "alt": "/alt"}

        router = Router()
        router.add_page(PageWithRoutes)

        self.assertEqual(len(router.routes), 2)
        match = router.match("/main")
        assert match is not None
        self.assertEqual(match[0], PageWithRoutes)
        self.assertEqual(match[2], "main")

    def test_router_remove_routes_for_file(self) -> None:
        class PageA(MockPage):
            __file_path__ = "file_a.pywire"
            __route__ = "/a"

        class PageB(MockPage):
            __file_path__ = "file_b.pywire"
            __route__ = "/b"

        router = Router()
        router.add_page(PageA)
        router.add_page(PageB)

        self.assertEqual(len(router.routes), 2)
        router.remove_routes_for_file("file_a.pywire")
        self.assertEqual(len(router.routes), 1)
        self.assertEqual(router.routes[0].page_class, PageB)


if __name__ == "__main__":
    unittest.main()

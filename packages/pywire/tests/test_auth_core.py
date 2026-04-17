"""Tests for pywire.auth core primitives."""

from __future__ import annotations

import asyncio
import unittest

from pywire.auth import (
    ANONYMOUS,
    AuthContext,
    AuthEvent,
    Claim,
    ClaimsPrincipal,
    MemoryAuthChannel,
    PolicyContext,
    PolicyEngine,
    deserialize,
    get_auth_context,
    read_principal_from_session,
    reset_auth_context,
    run_auth_guard,
    serialize,
    set_auth_context,
    write_principal_to_session,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestPrincipal(unittest.TestCase):
    def test_anonymous_sentinel(self) -> None:
        self.assertFalse(ANONYMOUS.is_authenticated)
        self.assertEqual(ANONYMOUS.claims, [])
        self.assertEqual(ANONYMOUS.name, "")

    def test_has_claim_type_only(self) -> None:
        p = ClaimsPrincipal(
            is_authenticated=True,
            claims=[Claim(type="role", value="admin")],
        )
        self.assertTrue(p.has_claim("role"))
        self.assertFalse(p.has_claim("email"))

    def test_has_claim_exact_value(self) -> None:
        p = ClaimsPrincipal(
            is_authenticated=True,
            claims=[Claim(type="role", value="admin")],
        )
        self.assertTrue(p.has_claim("role", "admin"))
        self.assertFalse(p.has_claim("role", "editor"))

    def test_claim_value_first_match(self) -> None:
        p = ClaimsPrincipal(
            claims=[
                Claim(type="role", value="admin"),
                Claim(type="role", value="editor"),
            ]
        )
        self.assertEqual(p.claim_value("role"), "admin")
        self.assertIsNone(p.claim_value("missing"))


class TestPolicyEngine(unittest.TestCase):
    def test_register_function(self) -> None:
        engine = PolicyEngine()

        async def admin_only(ctx: PolicyContext) -> bool:
            return ctx.principal.has_claim("role", "admin")

        engine.add_policy("AdminOnly", fn=admin_only)

        admin = ClaimsPrincipal(
            is_authenticated=True,
            claims=[Claim(type="role", value="admin")],
        )
        editor = ClaimsPrincipal(
            is_authenticated=True,
            claims=[Claim(type="role", value="editor")],
        )

        self.assertTrue(
            _run(engine.evaluate("AdminOnly", PolicyContext(principal=admin)))
        )
        self.assertFalse(
            _run(engine.evaluate("AdminOnly", PolicyContext(principal=editor)))
        )

    def test_requires_claim_declarative(self) -> None:
        engine = PolicyEngine()
        engine.add_policy("Pro", requires_claim=("tier", "pro"))

        pro = ClaimsPrincipal(
            is_authenticated=True,
            claims=[Claim(type="tier", value="pro")],
        )
        free = ClaimsPrincipal(
            is_authenticated=True,
            claims=[Claim(type="tier", value="free")],
        )

        self.assertTrue(_run(engine.evaluate("Pro", PolicyContext(principal=pro))))
        self.assertFalse(_run(engine.evaluate("Pro", PolicyContext(principal=free))))

    def test_requires_authenticated(self) -> None:
        engine = PolicyEngine()
        engine.add_policy("LoggedIn", requires_authenticated=True)

        p = ClaimsPrincipal(is_authenticated=True)
        self.assertTrue(
            _run(engine.evaluate("LoggedIn", PolicyContext(principal=p)))
        )
        self.assertFalse(
            _run(engine.evaluate("LoggedIn", PolicyContext(principal=ANONYMOUS)))
        )

    def test_decorator_form(self) -> None:
        engine = PolicyEngine()

        @engine.policy("HasEmail")
        def has_email(ctx: PolicyContext) -> bool:
            return ctx.principal.has_claim("email")

        p = ClaimsPrincipal(
            is_authenticated=True,
            claims=[Claim(type="email", value="a@b.c")],
        )
        self.assertTrue(_run(engine.evaluate("HasEmail", PolicyContext(principal=p))))

    def test_unknown_policy_raises(self) -> None:
        engine = PolicyEngine()
        with self.assertRaises(KeyError):
            _run(engine.evaluate("Missing", PolicyContext(principal=ANONYMOUS)))

    def test_add_policy_requires_exactly_one_form(self) -> None:
        engine = PolicyEngine()
        with self.assertRaises(ValueError):
            engine.add_policy("Bad")
        with self.assertRaises(ValueError):
            engine.add_policy(
                "Bad", requires_authenticated=True, requires_claim=("a", "b")
            )


class TestMemoryAuthChannel(unittest.TestCase):
    def test_update_and_revoke_fanout(self) -> None:
        async def scenario() -> list[AuthEvent]:
            channel = MemoryAuthChannel()
            events: list[AuthEvent] = []

            async with channel.subscribe("u1") as sub:
                # Kick off producers concurrently
                async def produce() -> None:
                    await asyncio.sleep(0)  # give subscribe a chance to register
                    await channel.update_principal(
                        "u1", claims=[Claim(type="role", value="admin")]
                    )
                    await channel.revoke("u1")

                producer = asyncio.create_task(produce())

                async for event in sub:
                    events.append(event)
                    if len(events) == 2:
                        break

                await producer

            return events

        events = asyncio.new_event_loop().run_until_complete(scenario())
        self.assertEqual([e.kind for e in events], ["update", "revoke"])
        self.assertEqual(events[0].claims, [Claim(type="role", value="admin")])

    def test_unsubscribe_on_context_exit(self) -> None:
        async def scenario() -> int:
            channel = MemoryAuthChannel()
            async with channel.subscribe("u1"):
                pass
            return len(channel._subscribers)

        self.assertEqual(
            asyncio.new_event_loop().run_until_complete(scenario()), 0
        )


class TestAuthGuard(unittest.TestCase):
    def _page(self, **attrs):
        cls = type("P", (), attrs)
        page = cls()
        return page

    def test_unprotected_allows(self) -> None:
        page = self._page()
        self.assertIsNone(_run(run_auth_guard(page)))

    def test_bare_auth_denies_anonymous(self) -> None:
        page = self._page(__auth_required__=True)
        page.user = ANONYMOUS
        resp = _run(run_auth_guard(page))
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/login")

    def test_bare_auth_allows_authenticated(self) -> None:
        page = self._page(__auth_required__=True)
        page.user = ClaimsPrincipal(is_authenticated=True)
        self.assertIsNone(_run(run_auth_guard(page)))

    def test_custom_redirect(self) -> None:
        page = self._page(
            __auth_required__=True, __auth_redirect__="/sign-in"
        )
        page.user = ANONYMOUS
        resp = _run(run_auth_guard(page))
        assert resp is not None
        self.assertEqual(resp.headers["location"], "/sign-in")

    def test_claims_check(self) -> None:
        page = self._page(
            __auth_required__=True,
            __auth_claims__=[("role", "admin")],
        )
        page.user = ClaimsPrincipal(
            is_authenticated=True,
            claims=[Claim(type="role", value="editor")],
        )
        resp = _run(run_auth_guard(page))
        self.assertIsNotNone(resp)

        page.user = ClaimsPrincipal(
            is_authenticated=True,
            claims=[Claim(type="role", value="admin")],
        )
        self.assertIsNone(_run(run_auth_guard(page)))

    def test_named_policy_allows(self) -> None:
        page = self._page(
            __auth_required__=True, __auth_policy__="AdminOnly"
        )
        page.user = ClaimsPrincipal(
            is_authenticated=True,
            claims=[Claim(type="role", value="admin")],
        )

        async def scenario():
            engine = PolicyEngine()
            engine.add_policy("AdminOnly", requires_claim=("role", "admin"))
            ctx = AuthContext(
                principal=page.user, engine=engine, channel=MemoryAuthChannel()
            )
            token = set_auth_context(ctx)
            try:
                return await run_auth_guard(page)
            finally:
                reset_auth_context(token)

        self.assertIsNone(
            asyncio.new_event_loop().run_until_complete(scenario())
        )

    def test_named_policy_denies(self) -> None:
        page = self._page(
            __auth_required__=True, __auth_policy__="AdminOnly"
        )
        page.user = ClaimsPrincipal(is_authenticated=True)

        async def scenario():
            engine = PolicyEngine()
            engine.add_policy("AdminOnly", requires_claim=("role", "admin"))
            ctx = AuthContext(
                principal=page.user, engine=engine, channel=MemoryAuthChannel()
            )
            token = set_auth_context(ctx)
            try:
                return await run_auth_guard(page)
            finally:
                reset_auth_context(token)

        resp = asyncio.new_event_loop().run_until_complete(scenario())
        self.assertIsNotNone(resp)

    def test_named_policy_missing_engine_fails_closed(self) -> None:
        page = self._page(
            __auth_required__=True, __auth_policy__="AdminOnly"
        )
        page.user = ClaimsPrincipal(is_authenticated=True)
        self.assertIsNotNone(_run(run_auth_guard(page)))

    def test_unknown_policy_fails_closed(self) -> None:
        page = self._page(
            __auth_required__=True, __auth_policy__="DoesNotExist"
        )
        page.user = ClaimsPrincipal(is_authenticated=True)

        async def scenario():
            engine = PolicyEngine()
            ctx = AuthContext(
                principal=page.user, engine=engine, channel=MemoryAuthChannel()
            )
            token = set_auth_context(ctx)
            try:
                return await run_auth_guard(page)
            finally:
                reset_auth_context(token)

        self.assertIsNotNone(
            asyncio.new_event_loop().run_until_complete(scenario())
        )


class TestAuthContextVar(unittest.TestCase):
    def test_get_default_none(self) -> None:
        self.assertIsNone(get_auth_context())

    def test_set_and_reset(self) -> None:
        engine = PolicyEngine()
        channel = MemoryAuthChannel()
        ctx = AuthContext(principal=ANONYMOUS, engine=engine, channel=channel)
        token = set_auth_context(ctx)
        try:
            self.assertIs(get_auth_context(), ctx)
        finally:
            reset_auth_context(token)
        self.assertIsNone(get_auth_context())


class TestSessionSerialization(unittest.TestCase):
    def test_roundtrip(self) -> None:
        p = ClaimsPrincipal(
            is_authenticated=True,
            name="Alice",
            user_id="google:123",
            claims=[
                Claim(type="role", value="admin"),
                Claim(type="email", value="a@b.c"),
            ],
            raw={"sub": "123", "iss": "google"},
        )
        data = serialize(p)
        restored = deserialize(data)
        self.assertEqual(restored.is_authenticated, True)
        self.assertEqual(restored.name, "Alice")
        self.assertEqual(restored.user_id, "google:123")
        self.assertEqual(len(restored.claims), 2)
        self.assertEqual(restored.claims[0].type, "role")
        self.assertEqual(restored.raw["iss"], "google")

    def test_read_from_empty_session(self) -> None:
        self.assertIsNone(read_principal_from_session(None))
        self.assertIsNone(read_principal_from_session({}))

    def test_write_read_session(self) -> None:
        session: dict = {}
        p = ClaimsPrincipal(is_authenticated=True, name="Bob")
        write_principal_to_session(session, p)
        restored = read_principal_from_session(session)
        assert restored is not None
        self.assertEqual(restored.name, "Bob")


if __name__ == "__main__":
    unittest.main()

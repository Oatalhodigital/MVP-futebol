import asyncio
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.config import SCORES365_SELECTORS, SCORES365_URLS, get_settings
from app.models import LastMatch, LiveState, MatchData, MatchInput, MatchStatus, TeamStats
from app.providers.base import DataProvider
from app.providers.utils import (
    contains_team,
    extract_minute,
    extract_score_with_teams,
    extract_stat_pairs,
    normalize,
    status_from_text,
)


class BrowserNavigationProvider(DataProvider):
    """Real 365Scores provider using Playwright headless navigation.

    Navigates the public site, searches for the requested fixture and extracts
    live or scheduled match information. If the site changes, only the
    selectors in ``app.config`` need to be updated.
    """

    name = "browser_navigation"

    def __init__(
        self,
        selectors: dict[str, str] | None = None,
        urls: dict[str, str] | None = None,
    ):
        self.selectors = selectors or SCORES365_SELECTORS
        self.urls = urls or SCORES365_URLS
        self.settings = get_settings()

    async def get_match_stats(self, match_input: MatchInput) -> MatchData:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._scrape_with_fresh_loop, match_input)
        except Exception as exc:
            return MatchData(
                team_a=match_input.team_a,
                team_b=match_input.team_b,
                competition=match_input.competition,
                match_datetime=match_input.match_datetime,
                status=MatchStatus.UNKNOWN,
                source=self.name,
                completeness=0.0,
                updated_at=datetime.utcnow(),
                raw_metadata={"error": repr(exc)},
            )

    def _scrape_with_fresh_loop(self, match_input: MatchInput) -> MatchData:
        """Run the async Playwright code in a dedicated thread/event loop."""
        return asyncio.run(self._scrape_with_browser(match_input))

    async def _scrape_with_browser(self, match_input: MatchInput) -> MatchData:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.settings.playwright_headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="pt-BR",
            )
            page = await context.new_page()
            data = await self._scrape(page, match_input)
            await browser.close()
            return data

    async def _scrape(self, page, match_input: MatchInput) -> MatchData:
        settings = self.settings
        await page.goto(
            self.urls["home"],
            wait_until="domcontentloaded",
            timeout=int(settings.provider_timeout_seconds * 1000),
        )
        await self._accept_cookies(page)
        await page.wait_for_timeout(1500)

        match_url = await self._find_match_url(page, match_input)
        if match_url:
            await page.goto(
                match_url,
                wait_until="domcontentloaded",
                timeout=int(settings.provider_timeout_seconds * 1000),
            )
            await page.wait_for_timeout(2500)
        else:
            # Fallback direct search URL if available
            query = quote(f"{match_input.team_a} {match_input.team_b}")
            await page.goto(
                f"{self.urls['search']}?q={query}",
                wait_until="domcontentloaded",
                timeout=int(settings.provider_timeout_seconds * 1000),
            )
            await page.wait_for_timeout(2500)

        body_text = (await page.locator("body").text_content() or "").lower()
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        status_str, period = status_from_text(body_text)
        try:
            status = MatchStatus(status_str) if status_str else MatchStatus.UNKNOWN
        except ValueError:
            status = MatchStatus.UNKNOWN

        score_a, score_b = extract_score_with_teams(
            body_text, match_input.team_a, match_input.team_b
        )
        minute = extract_minute(body_text)
        stats = extract_stat_pairs(body_text)

        # Avoid treating the main score as a stat pair
        stats.pop("score", None)

        live = LiveState(
            status=status,
            minute=minute,
            period=period,
            score_a=score_a,
            score_b=score_b,
            corners_a=_first(stats.get("corners")),
            corners_b=_second(stats.get("corners")),
            shots_a=_first(stats.get("shots")),
            shots_b=_second(stats.get("shots")),
            shots_on_target_a=_first(stats.get("shots_on_target")),
            shots_on_target_b=_second(stats.get("shots_on_target")),
            possession_a=_first(stats.get("possession")),
            possession_b=_second(stats.get("possession")),
            cards_yellow_a=_first(stats.get("yellow_cards")),
            cards_yellow_b=_second(stats.get("yellow_cards")),
            cards_red_a=_first(stats.get("red_cards")),
            cards_red_b=_second(stats.get("red_cards")),
        )

        form_a = await self._extract_team_form(page, soup, match_input.team_a)
        form_b = await self._extract_team_form(page, soup, match_input.team_b)
        h2h = self._extract_h2h(soup, match_input.team_a, match_input.team_b)

        team_a_stats = self._team_stats_from_matches(match_input.team_a, form_a)
        team_b_stats = self._team_stats_from_matches(match_input.team_b, form_b)

        completeness = self._completeness(live, team_a_stats, team_b_stats, h2h)

        return MatchData(
            team_a=match_input.team_a,
            team_b=match_input.team_b,
            competition=match_input.competition or self._extract_competition(soup, body_text),
            match_datetime=match_input.match_datetime,
            status=status,
            score_a=live.score_a,
            score_b=live.score_b,
            minute=live.minute,
            live=live,
            team_a_stats=team_a_stats,
            team_b_stats=team_b_stats,
            h2h=h2h,
            source=self.name,
            completeness=completeness,
            updated_at=datetime.utcnow(),
            raw_metadata={"page_text_sample": body_text[:1500]},
        )

    async def _accept_cookies(self, page) -> None:
        try:
            btn = page.locator(self.selectors["accept_cookies_button"]).first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass

    async def _find_match_url(self, page, match_input: MatchInput) -> str | None:
        """Try to search inside 365Scores and return the most promising match link."""
        try:
            input_loc = page.locator(self.selectors["search_input"]).first
            if await input_loc.is_visible(timeout=3000):
                await input_loc.fill(f"{match_input.team_a} {match_input.team_b}")
                await input_loc.press("Enter")
                await page.wait_for_timeout(2500)
        except Exception:
            pass

        home = self.urls["home"].rstrip("/")
        candidates = []
        try:
            for link in await page.locator("a").all():
                href = await link.get_attribute("href") or ""
                if not href:
                    continue
                lower = href.lower()
                if any(s in lower for s in ["/match/", "/jogo/", "/game/", "/partida/"]):
                    if href.startswith("/"):
                        href = home + href
                    text = (await link.text_content() or "").lower()
                    if contains_team(text, match_input.team_a) and contains_team(
                        text, match_input.team_b
                    ):
                        score_a, score_b = extract_score_with_teams(
                            text, match_input.team_a, match_input.team_b
                        )
                        candidates.append((href, text, score_a, score_b))
        except Exception:
            pass

        if not candidates:
            return None

        # Prefer candidate that already shows a score (likely live/finished)
        candidates.sort(
            key=lambda c: (
                1 if c[2] is not None and c[3] is not None else 0,
                len(c[1]),
            ),
            reverse=True,
        )
        return candidates[0][0]

    async def _extract_team_form(
        self, page, soup: BeautifulSoup, team_name: str
    ) -> list[LastMatch]:
        """Try to navigate to the team page on 365Scores to find recent fixtures."""
        home = self.urls["home"].rstrip("/")
        links = []
        for a in soup.find_all("a"):
            text = a.get_text(" ", strip=True)
            if contains_team(text, team_name):
                href = a.get("href") or ""
                if href.startswith("/"):
                    href = home + href
                if href:
                    links.append(href)

        for href in links[:5]:
            try:
                await page.goto(
                    href,
                    wait_until="domcontentloaded",
                    timeout=20000,
                )
                await page.wait_for_timeout(2000)
                text = (await page.locator("body").text_content() or "").lower()
                matches = self._parse_match_rows(text, team_name)
                if len(matches) >= 3:
                    return matches
            except Exception:
                continue

        # Fallback: parse whatever is on current page
        text = (await page.locator("body").text_content() or "").lower()
        return self._parse_match_rows(text, team_name)

    def _parse_match_rows(self, text: str, team_name: str, max_rows: int = 10) -> list[LastMatch]:
        matches: list[LastMatch] = []
        seen: set[tuple[str, int, int]] = set()
        score_regex = re.compile(r"(\d{1,2})\s*[-–:]\s*(\d{1,2})")

        for score_m in score_regex.finditer(text):
            start = max(0, score_m.start() - 120)
            end = min(len(text), score_m.end() + 120)
            ctx = text[start:end]

            if not contains_team(ctx, team_name):
                continue

            g_home = int(score_m.group(1))
            g_away = int(score_m.group(2))

            # Try to find the two team names around the score in this window
            team_pattern = re.compile(
                r"([a-z0-9áéíóúãõç\s'.\-]{3,50}?)\s+" + re.escape(score_m.group(0)) + r"\s+([a-z0-9áéíóúãõç\s'.\-]{3,50}?)",
                re.IGNORECASE,
            )
            m = team_pattern.search(ctx)
            if not m:
                continue
            left = m.group(1).strip()
            right = m.group(2).strip()

            team_on_left = contains_team(left, team_name)
            team_on_right = contains_team(right, team_name)
            if team_on_left and not team_on_right:
                opponent = right
                venue = "home"
                gf, ga = g_home, g_away
            elif team_on_right and not team_on_left:
                opponent = left
                venue = "away"
                gf, ga = g_away, g_home
            else:
                continue

            key = (normalize(opponent), gf, ga)
            if key in seen:
                continue
            seen.add(key)
            result = "W" if gf > ga else ("D" if gf == ga else "L")
            matches.append(
                LastMatch(
                    opponent=opponent.strip().title(),
                    venue=venue,
                    goals_for=gf,
                    goals_against=ga,
                    result=result,
                )
            )
            if len(matches) >= max_rows:
                break

        return matches

    def _extract_h2h(
        self, soup: BeautifulSoup, team_a: str, team_b: str
    ) -> list[LastMatch]:
        text = soup.get_text(" ", strip=True).lower()
        # Crude extraction: matches between the two teams anywhere on the page
        rows = self._parse_match_rows(text, team_a, max_rows=20)
        return [r for r in rows if contains_team(r.opponent.lower(), team_b)][:5]

    def _team_stats_from_matches(
        self, team: str, matches: list[LastMatch]
    ) -> TeamStats | None:
        if not matches:
            return None
        n = len(matches)
        total_gf = sum(m.goals_for for m in matches)
        total_ga = sum(m.goals_against for m in matches)
        return TeamStats(
            name=team,
            recent_matches=matches,
            avg_goals_scored_ft=round(total_gf / n, 2),
            avg_goals_conceded_ft=round(total_ga / n, 2),
            avg_goals_scored_ht=round((total_gf * 0.45) / n, 2),
            avg_goals_conceded_ht=round((total_ga * 0.45) / n, 2),
            avg_corners=round(4.0 + (total_gf / n) * 0.8, 2),
            avg_shots=round(9.0 + (total_gf / n) * 1.5, 2),
        )

    def _extract_competition(self, soup: BeautifulSoup, text: str) -> str | None:
        for el in soup.find_all(["h1", "h2", "title"]):
            txt = el.get_text(" ", strip=True)
            lowered = txt.lower()
            if any(x in lowered for x in ["campeonato", "liga", "série", "copa", "champions"]):
                return txt
        return None

    def _completeness(
        self,
        live: LiveState,
        a: TeamStats | None,
        b: TeamStats | None,
        h2h: list[LastMatch],
    ) -> float:
        score = 0.0
        if live and live.status and live.status != MatchStatus.UNKNOWN:
            score += 0.35
        if live.score_a is not None and live.score_b is not None:
            score += 0.10
        if live.minute is not None:
            score += 0.05
        if any(
            v is not None
            for v in [
                live.corners_a,
                live.shots_a,
                live.shots_on_target_a,
                live.possession_a,
            ]
        ):
            score += 0.10
        if a and len(a.recent_matches) >= 3:
            score += 0.15
        if b and len(b.recent_matches) >= 3:
            score += 0.15
        if h2h:
            score += 0.10
        return round(min(score, 1.0), 2)


def _first(pair: tuple[int, int] | None) -> int | None:
    return pair[0] if pair else None


def _second(pair: tuple[int, int] | None) -> int | None:
    return pair[1] if pair else None

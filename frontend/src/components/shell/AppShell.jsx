import { Outlet } from "react-router-dom";
import NavBar from "./NavBar.jsx";
import SpineRegion from "./SpineRegion.jsx";
import StatusStrip from "./StatusStrip.jsx";

/**
 * AppShell — §4.
 *
 * Nav on top, route content in the middle, status strip pinned to the bottom.
 * The shell owns the viewport: the page itself never scrolls, only the content
 * region does, so the status strip cannot be scrolled out of sight. A strip
 * that can disappear is a strip nobody trusts.
 *
 * The cursor spine (§3) sits between the nav and the content region, on every
 * page, because it is not a control belonging to one screen — it is the frame
 * every screen is read through.
 */
export default function AppShell() {
  return (
    <div className="flex h-dvh flex-col bg-abyss">
      <NavBar />
      <SpineRegion />
      <main className="min-h-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
      <StatusStrip />
    </div>
  );
}

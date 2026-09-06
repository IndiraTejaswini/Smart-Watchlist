import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Num from "../components/Num.jsx";

const TICKERS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "AXISBANK", "TATAMOTORS", "IDEA", "SUNPHARMA"];

function TickerColumn() {
  return (
    <div className="space-y-6 opacity-40">
      {TICKERS.map((ticker, index) => (
        <div key={ticker} className="flex max-w-sm items-center justify-between border-b border-hairline pb-3">
          <span className="num text-ui text-slate">{ticker}</span>
          <Num value={index % 2 ? 1.4 : -0.8} kind="percent" dp={1} tone="direction" />
        </div>
      ))}
    </div>
  );
}

export default function Auth({ mode = "login" }) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  function openDemo() {
    window.localStorage.setItem("smart-watchlist-user", "demo");
    navigate("/brief");
  }
  return (
    <main className="grid min-h-dvh md:grid-cols-2">
      <section className="flex items-center justify-center bg-abyss px-6 py-12">
        <div className="w-full max-w-[360px]">
          <Link to="/" className="text-ui text-slate">Smart Watchlist</Link>
          <h1 className="mt-12 font-prose text-section text-chalk">{mode === "login" ? "Sign in" : "Create an account"}</h1>
          <p className="mt-3 text-ui text-slate">The demo is ready with a populated watchlist.</p>
          <button type="button" onClick={openDemo} className="mt-8 w-full rounded-[3px] border border-chalk bg-chalk px-4 py-3 text-ui text-abyss">
            Open the demo account
          </button>
          <div className="my-8 border-t border-hairline" />
          <form onSubmit={(event) => { event.preventDefault(); navigate("/brief"); }} className="space-y-5">
            <label className="block text-ui text-slate">Email<input value={email} onChange={(event) => setEmail(event.target.value)} type="email" className="mt-2 w-full rounded-[3px] border border-hairline bg-panel px-3 py-3 text-ui text-chalk outline-none" /></label>
            <label className="block text-ui text-slate">Password<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" className="mt-2 w-full rounded-[3px] border border-hairline bg-panel px-3 py-3 text-ui text-chalk outline-none" /></label>
            <button type="submit" className="w-full rounded-[3px] border border-hairline px-4 py-3 text-ui text-slate hover:border-chalk hover:text-chalk">Continue</button>
          </form>
          <p className="mt-6 text-ui text-slate">{mode === "login" ? "Need an account?" : "Already registered?"} <Link to={mode === "login" ? "/register" : "/login"} className="text-chalk underline decoration-hairline underline-offset-4">{mode === "login" ? "Register" : "Sign in"}</Link></p>
        </div>
      </section>
      <aside className="hidden bg-panel p-16 md:block"><TickerColumn /></aside>
    </main>
  );
}

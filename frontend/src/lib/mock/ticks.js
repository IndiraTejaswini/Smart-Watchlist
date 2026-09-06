import { useQuoteStore } from "../../store/useQuoteStore.js";

let timer;

export function startMockTickStream(symbols) {
  stopMockTickStream();
  const active = () => symbols.filter((symbol) => useQuoteStore.getState().quotes[symbol]);
  timer = setInterval(() => {
    active().forEach((symbol) => {
      const quote = useQuoteStore.getState().quotes[symbol];
      const delta = (Math.random() - 0.5) * Math.max(0.02, quote.ltp * 0.0004);
      const ltp = Number((quote.ltp + delta).toFixed(2));
      useQuoteStore.getState().applyTick(symbol, {
        ltp,
        change: Number((quote.change + delta).toFixed(2)),
        chp: Number(((quote.chp + (delta / quote.ltp) * 100)).toFixed(2)),
      });
    });
  }, 1000);
  return stopMockTickStream;
}

export function stopMockTickStream() {
  if (timer) {
    clearInterval(timer);
    timer = undefined;
  }
}


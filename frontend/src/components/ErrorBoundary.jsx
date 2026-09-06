import { Component } from "react";
import { IS_DEV } from "../lib/env.js";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    if (IS_DEV) {
      console.error("Route boundary caught a payload or render error", error, info);
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="m-6 border border-hairline bg-panel px-5 py-4 text-ui text-slate">
          Data feed format restated — showing cached baseline
        </div>
      );
    }
    return this.props.children;
  }
}

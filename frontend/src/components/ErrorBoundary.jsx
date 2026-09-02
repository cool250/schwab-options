import { Component } from "react";

// A render error anywhere below this (e.g. bad market data reaching a
// .toFixed() call) unmounts the whole app with no error boundary in place —
// which reads to a user as the page having crashed/reloaded. This catches
// that and swaps in a small recoverable message instead of a blank page.
export default class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Uncaught render error:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="error-boundary">
          <p>Something went wrong displaying this page.</p>
          <button className="btn btn-secondary" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

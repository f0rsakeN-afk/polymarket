"use client"

import React, { Component, ReactNode } from "react"
import { Button } from "@workspace/ui/components/button"

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error?: Error
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false }
    this.handleReset = this.handleReset.bind(this)
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  handleReset() {
    this.setState({ hasError: false })
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <p className="text-sm font-medium text-foreground mb-1">Something went wrong</p>
          <p className="text-xs text-muted-foreground mb-4">
            {this.state.error?.message ?? "An unexpected error occurred"}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={this.handleReset}
          >
            Try again
          </Button>
        </div>
      )
    }
    return this.props.children
  }
}

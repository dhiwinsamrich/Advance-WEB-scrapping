"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Activity, ArrowLeft, Code, Zap, Database, Globe, Terminal } from "lucide-react"
import Link from "next/link"

export default function DocsPage() {
    return (
        <div className="min-h-screen bg-background text-foreground">
            {/* Header */}
            <header className="sticky top-0 z-10 w-full border-b bg-background/95 backdrop-blur">
                <div className="container flex h-16 items-center justify-between mx-auto px-4 max-w-4xl">
                    <Link href="/" className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors">
                        <ArrowLeft className="h-4 w-4" />
                        <span className="text-sm font-medium">Back to App</span>
                    </Link>
                    <div className="flex items-center gap-2">
                        <img
                            src="/icon.png"
                            alt="Web Scraper Logo"
                            className="h-8 w-8 rounded-full object-cover"
                        />
                        <span className="text-lg font-bold">Documentation</span>
                    </div>
                    <span className="text-xs text-muted-foreground">
                        by <span className="font-semibold text-foreground">Dhiwin Samrich</span>
                    </span>
                </div>
            </header>

            <main className="container mx-auto px-4 max-w-4xl py-12 space-y-12">
                {/* Hero */}
                <div className="text-center space-y-4">
                    <h1 className="text-4xl font-bold tracking-tight">Anti-Fail WebScraper</h1>
                    <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
                        A production-ready web scraping solution with automatic retry, Selenium fallback,
                        and real-time log streaming.
                    </p>
                </div>

                {/* Quick Start */}
                <Card>
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <Zap className="h-5 w-5 text-amber-500" />
                            Quick Start
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <div className="space-y-2">
                            <p className="font-medium">1. Enter Target URL</p>
                            <p className="text-sm text-muted-foreground">Provide the website URL you want to scrape (e.g., https://example.com)</p>
                        </div>
                        <div className="space-y-2">
                            <p className="font-medium">2. Set Crawl Depth</p>
                            <p className="text-sm text-muted-foreground">Higher depth means more pages but longer processing time</p>
                        </div>
                        <div className="space-y-2">
                            <p className="font-medium">3. Click Start Extraction</p>
                            <p className="text-sm text-muted-foreground">Watch real-time logs as pages are scraped</p>
                        </div>
                        <div className="space-y-2">
                            <p className="font-medium">4. Download or View Data</p>
                            <p className="text-sm text-muted-foreground">Export JSON or use the built-in viewer to explore results</p>
                        </div>
                    </CardContent>
                </Card>

                {/* API Endpoints */}
                <Card>
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <Code className="h-5 w-5 text-blue-500" />
                            FastAPI Endpoints
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-6">
                        {/* POST /start */}
                        <div className="border rounded-lg p-4 space-y-3">
                            <div className="flex items-center gap-2">
                                <span className="px-2 py-1 text-xs font-bold bg-green-500/20 text-green-400 rounded">POST</span>
                                <code className="font-mono text-sm">/start</code>
                            </div>
                            <p className="text-sm text-muted-foreground">Starts the web scraping process</p>
                            <div className="bg-zinc-900 rounded p-3 font-mono text-xs overflow-x-auto">
                                <p className="text-zinc-500">{`// Request Body`}</p>
                                <pre className="text-zinc-300">{`{
  "url": "https://example.com",
  "max_depth": 2
}`}</pre>
                            </div>
                            <div className="bg-zinc-900 rounded p-3 font-mono text-xs overflow-x-auto">
                                <p className="text-zinc-500">{`// Response`}</p>
                                <pre className="text-zinc-300">{`{
  "message": "Scraper started",
  "url": "https://example.com"
}`}</pre>
                            </div>
                        </div>

                        {/* GET /status */}
                        <div className="border rounded-lg p-4 space-y-3">
                            <div className="flex items-center gap-2">
                                <span className="px-2 py-1 text-xs font-bold bg-blue-500/20 text-blue-400 rounded">GET</span>
                                <code className="font-mono text-sm">/status</code>
                            </div>
                            <p className="text-sm text-muted-foreground">Returns current scraper status</p>
                            <div className="bg-zinc-900 rounded p-3 font-mono text-xs overflow-x-auto">
                                <p className="text-zinc-500">{`// Response`}</p>
                                <pre className="text-zinc-300">{`{
  "is_running": true,
  "current_url": "https://example.com/page",
  "logs_path": "/app/logs/scraper.log"
}`}</pre>
                            </div>
                        </div>

                        {/* POST /stop */}
                        <div className="border rounded-lg p-4 space-y-3">
                            <div className="flex items-center gap-2">
                                <span className="px-2 py-1 text-xs font-bold bg-red-500/20 text-red-400 rounded">POST</span>
                                <code className="font-mono text-sm">/stop</code>
                            </div>
                            <p className="text-sm text-muted-foreground">Stops the active scraping process</p>
                            <div className="bg-zinc-900 rounded p-3 font-mono text-xs overflow-x-auto">
                                <p className="text-zinc-500">{`// Response`}</p>
                                <pre className="text-zinc-300">{`{ "message": "Stop signal sent" }`}</pre>
                            </div>
                        </div>

                        {/* GET /download */}
                        <div className="border rounded-lg p-4 space-y-3">
                            <div className="flex items-center gap-2">
                                <span className="px-2 py-1 text-xs font-bold bg-blue-500/20 text-blue-400 rounded">GET</span>
                                <code className="font-mono text-sm">/download</code>
                            </div>
                            <p className="text-sm text-muted-foreground">Downloads scraped data as JSON file</p>
                            <p className="text-xs text-muted-foreground">Returns: <code>application/json</code> file</p>
                        </div>

                        {/* WebSocket /logs */}
                        <div className="border rounded-lg p-4 space-y-3">
                            <div className="flex items-center gap-2">
                                <span className="px-2 py-1 text-xs font-bold bg-purple-500/20 text-purple-400 rounded">WS</span>
                                <code className="font-mono text-sm">/logs</code>
                            </div>
                            <p className="text-sm text-muted-foreground">Real-time log streaming via WebSocket</p>
                            <div className="bg-zinc-900 rounded p-3 font-mono text-xs overflow-x-auto">
                                <p className="text-zinc-500">{`// Connect`}</p>
                                <pre className="text-zinc-300">{`const ws = new WebSocket("wss://your-api.com/logs")
ws.onmessage = (event) => console.log(event.data)`}</pre>
                            </div>
                        </div>
                    </CardContent>
                </Card>

                {/* Features */}
                <Card>
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <Database className="h-5 w-5 text-emerald-500" />
                            Key Features
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="grid sm:grid-cols-2 gap-4">
                            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
                                <Globe className="h-5 w-5 text-blue-400 mt-0.5" />
                                <div>
                                    <p className="font-medium text-sm">Static + Dynamic Scraping</p>
                                    <p className="text-xs text-muted-foreground">Automatic fallback to Selenium for JavaScript-heavy sites</p>
                                </div>
                            </div>
                            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
                                <Terminal className="h-5 w-5 text-amber-400 mt-0.5" />
                                <div>
                                    <p className="font-medium text-sm">Real-time Logs</p>
                                    <p className="text-xs text-muted-foreground">WebSocket-powered live log streaming</p>
                                </div>
                            </div>
                            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
                                <Zap className="h-5 w-5 text-purple-400 mt-0.5" />
                                <div>
                                    <p className="font-medium text-sm">Anti-Detection</p>
                                    <p className="text-xs text-muted-foreground">Random user agents and stealth mode</p>
                                </div>
                            </div>
                            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
                                <Code className="h-5 w-5 text-emerald-400 mt-0.5" />
                                <div>
                                    <p className="font-medium text-sm">JSON Viewer</p>
                                    <p className="text-xs text-muted-foreground">Built-in interactive data explorer</p>
                                </div>
                            </div>
                        </div>
                    </CardContent>
                </Card>

                {/* Footer */}
                <div className="text-center pt-8 border-t">
                    <p className="text-sm text-muted-foreground">
                        Created with ❤️ by <span className="font-semibold text-foreground">Dhiwin Samrich</span>
                    </p>
                    <div className="flex justify-center gap-4 mt-4">
                        <a
                            href="https://github.com/dhiwinsamrich/Advance-WEB-scrapping"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                        >
                            GitHub Repository
                        </a>
                    </div>
                </div>
            </main>
        </div>
    )
}

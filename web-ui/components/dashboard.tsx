"use client"

import * as React from "react"
import { useState, useEffect, useRef } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Terminal, Play, Square, Globe, Download, Pause, Activity, Layers, Clock } from "lucide-react"
import { cn } from "@/lib/utils"

// Helper to determine API Base URL
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// Helper to determine WebSocket URL
const getWebSocketUrl = () => {
    if (API_BASE_URL.startsWith("https")) {
        return API_BASE_URL.replace("https", "wss") + "/logs"
    }
    return API_BASE_URL.replace("http", "ws") + "/logs"
}

export default function Dashboard() {
    const [url, setUrl] = useState("")
    const [maxDepth, setMaxDepth] = useState(1)
    const [logs, setLogs] = useState<string[]>([])
    const [isRunning, setIsRunning] = useState(false)
    const [isConnected, setIsConnected] = useState(false)
    const [mounted, setMounted] = useState(false)
    const scrollRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        setMounted(true)
    }, [])

    // WebSocket Connection
    useEffect(() => {
        const wsUrl = getWebSocketUrl()
        console.log("Attempting WebSocket connection to:", wsUrl) // Debug log
        const ws = new WebSocket(wsUrl)

        ws.onopen = () => {
            console.log("WebSocket Connected")
            setIsConnected(true)
            setLogs((prev) => [...prev, JSON.stringify({ timestamp: new Date().toISOString(), level: "SYSTEM", message: "Connected to log stream..." })])
        }

        ws.onerror = (error) => {
            console.error("WebSocket Error:", error)
            setLogs((prev) => [...prev, JSON.stringify({ timestamp: new Date().toISOString(), level: "ERROR", message: `Connection failed to ${wsUrl}` })])
        }

        ws.onmessage = (event) => {
            setLogs((prev) => [...prev, event.data])
        }

        ws.onclose = () => {
            console.log("WebSocket Closed")
            setIsConnected(false)
        }

        return () => {
            ws.close()
        }
    }, [])

    // Auto-scroll logs
    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }
    }, [logs])

    const handleStart = async () => {
        if (!url) return
        setIsRunning(true)
        try {
            const res = await fetch(`${API_BASE_URL}/start`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url, max_depth: maxDepth }),
            })
            if (!res.ok) throw new Error("Failed to start")
            // Log added by server usually, but we can add immediate feedback
        } catch (e) {
            console.error(e)
            setIsRunning(false)
        }
    }

    const handleStop = async () => {
        try {
            await fetch(`${API_BASE_URL}/stop`, { method: "POST" })
            setIsRunning(false)
        } catch (e) {
            console.error(e)
        }
    }

    const handleDownload = () => {
        window.open(`${API_BASE_URL}/download`, "_blank")
    }

    // Parse logs for display
    const parsedLogs = logs.map(logStr => {
        try {
            return JSON.parse(logStr)
        } catch {
            return { message: logStr, level: "RAW", timestamp: new Date().toISOString() }
        }
    })

    if (!mounted) return null

    return (
        <div className="min-h-screen bg-background text-foreground selection:bg-zinc-200 selection:text-black">
            {/* Top Navigation / Header */}
            <header className="sticky top-0 z-10 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
                <div className="container flex h-16 items-center justify-between mx-auto px-4 max-w-7xl">
                    <div className="flex items-center gap-2">
                        <div className="h-8 w-8 bg-foreground rounded-lg flex items-center justify-center">
                            <Activity className="h-5 w-5 text-background" />
                        </div>
                        <div>
                            <h1 className="text-lg font-bold tracking-tight">Anti-Fail WebScraper</h1>
                            <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold">Production Ready</p>
                        </div>
                    </div>

                    <div className="flex items-center gap-4">
                        <div className="flex items-center gap-2 px-3 py-1 rounded-full border bg-muted/50">
                            <div className={cn("h-2 w-2 rounded-full animate-pulse", isConnected ? "bg-emerald-500" : "bg-rose-500")} />
                            <span className="text-xs font-medium text-muted-foreground">
                                {isConnected ? "System Online" : "Reconnecting..."}
                            </span>
                        </div>
                    </div>
                </div>
            </header>

            <main className="container mx-auto px-4 max-w-7xl py-8 space-y-8">
                <div className="grid lg:grid-cols-12 gap-8">
                    {/* Left Column: Controls */}
                    <div className="lg:col-span-4 space-y-6">
                        <Card className="border-2 shadow-sm">
                            <CardHeader className="pb-4">
                                <CardTitle>Configuration</CardTitle>
                                <CardDescription>Target parameters for the crawler engine.</CardDescription>
                            </CardHeader>
                            <CardContent className="space-y-6">
                                <div className="space-y-2">
                                    <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Target URL</label>
                                    <div className="relative group">
                                        <Globe className="absolute left-3 top-3 h-4 w-4 text-muted-foreground group-focus-within:text-foreground transition-colors" />
                                        <Input
                                            placeholder="https://example.com"
                                            className="pl-9 h-10 bg-muted/30 border-muted-foreground/20 focus-visible:ring-1 focus-visible:ring-ring"
                                            value={url}
                                            onChange={(e) => setUrl(e.target.value)}
                                        />
                                    </div>
                                </div>

                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Crawl Depth</label>
                                        <span className="text-xs font-mono bg-muted px-2 py-0.5 rounded">{maxDepth} Levels</span>
                                    </div>
                                    <div className="relative">
                                        <Layers className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                                        <Input
                                            type="number"
                                            min={1}
                                            max={10}
                                            className="pl-9 h-10 bg-muted/30 border-muted-foreground/20 focus-visible:ring-1 focus-visible:ring-ring"
                                            value={maxDepth}
                                            onChange={(e) => setMaxDepth(parseInt(e.target.value))}
                                        />
                                    </div>
                                    <p className="text-[10px] text-muted-foreground">Higher depth increases processing time exponentially.</p>
                                </div>
                            </CardContent>
                            <CardFooter className="flex flex-col gap-3 pt-2">
                                {!isRunning ? (
                                    <Button className="w-full h-10 font-semibold" onClick={handleStart} disabled={!url}>
                                        <Play className="mr-2 h-4 w-4 fill-current" /> Start Extraction
                                    </Button>
                                ) : (
                                    <Button variant="destructive" className="w-full h-10 font-semibold" onClick={handleStop}>
                                        <Square className="mr-2 h-4 w-4 fill-current" /> Stop Process
                                    </Button>
                                )}
                                <Button variant="outline" className="w-full h-10" onClick={handleDownload} disabled={logs.length === 0}>
                                    <Download className="mr-2 h-4 w-4" /> Download JSON Artifacts
                                </Button>
                            </CardFooter>
                        </Card>

                        {/* Status Card (Placeholder for real stats) */}
                        <Card className="bg-muted/10 border-dashed">
                            <CardContent className="p-4 flex items-center justify-between text-sm text-muted-foreground">
                                <div className="flex items-center gap-2">
                                    <Clock className="h-4 w-4" />
                                    <span>Session Duration</span>
                                </div>
                                <span className="font-mono">{isRunning ? "Active" : "Idle"}</span>
                            </CardContent>
                        </Card>
                    </div>

                    {/* Right Column: Terminal */}
                    <div className="lg:col-span-8 h-[600px] lg:h-auto min-h-[500px] flex flex-col">
                        <Card className="flex-1 flex flex-col border-2 shadow-sm overflow-hidden bg-zinc-950 text-zinc-50">
                            <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-900 bg-zinc-950">
                                <div className="flex items-center gap-2">
                                    <Terminal className="h-4 w-4 text-zinc-400" />
                                    <span className="text-sm font-medium text-zinc-300">Live Execution Log</span>
                                </div>
                                <div className="flex gap-1.5">
                                    <div className="h-3 w-3 rounded-full bg-red-500/20 border border-red-500/50" />
                                    <div className="h-3 w-3 rounded-full bg-yellow-500/20 border border-yellow-500/50" />
                                    <div className="h-3 w-3 rounded-full bg-green-500/20 border border-green-500/50" />
                                </div>
                            </div>

                            <div
                                ref={scrollRef}
                                className="flex-1 overflow-y-auto p-4 font-mono text-xs space-y-1 scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent"
                            >
                                {parsedLogs.length === 0 && (
                                    <div className="h-full flex flex-col items-center justify-center text-zinc-600 space-y-2">
                                        <Activity className="h-8 w-8 opacity-50" />
                                        <p>Ready to initialize sequence...</p>
                                    </div>
                                )}

                                {parsedLogs.map((log, i) => {
                                    const isError = log.level === "ERROR";
                                    const isWarning = log.level === "WARNING";
                                    const isInfo = log.level === "INFO";

                                    return (
                                        <div key={i} className={cn(
                                            "flex gap-4 py-1 border-b border-white/5 hover:bg-white/5 transition-colors items-start",
                                            isError && "bg-red-950/20 text-red-200 border-red-900/30",
                                        )}>
                                            <span className="shrink-0 w-[85px] text-zinc-500 select-none">
                                                {new Date(log.timestamp).toLocaleTimeString('en-GB', { hour12: false })}
                                            </span>

                                            <span className={cn(
                                                "shrink-0 w-[60px] font-bold select-none",
                                                isError && "text-red-500",
                                                isWarning && "text-amber-500",
                                                isInfo && "text-emerald-500",
                                                !isError && !isWarning && !isInfo && "text-blue-400"
                                            )}>
                                                {log.level}
                                            </span>

                                            <span className="flex-1 break-all text-zinc-300">
                                                {log.message}
                                            </span>
                                        </div>
                                    )
                                })}
                            </div>
                        </Card>
                    </div>
                </div>
            </main>
        </div>
    )
}

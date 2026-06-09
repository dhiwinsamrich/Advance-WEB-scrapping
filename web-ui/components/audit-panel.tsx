"use client"

import * as React from "react"
import { useState, useEffect, useRef } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
    Play, Square, Globe, Download, Activity, Terminal,
    CheckCircle2, XCircle, ChevronDown, ChevronRight,
    AlertTriangle, FileSearch, Link2, ShieldCheck, Info,
} from "lucide-react"
import { cn } from "@/lib/utils"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

const getAuditWsUrl = () =>
    API_BASE_URL.startsWith("https")
        ? API_BASE_URL.replace("https", "wss") + "/audit/logs"
        : API_BASE_URL.replace("http", "ws") + "/audit/logs"

// ── Types ─────────────────────────────────────────────────────────────────────

interface SitemapHygiene {
    total_urls: number
    over_url_limit: boolean
    over_size_limit: boolean
    duplicate_locs: string[]
    missing_lastmod: number
    redirect_entries: string[]
    non_200_entries: Record<string, number>
}

interface AuditReport {
    root_url: string
    covered: string[]
    missing_from_sitemap: string[]
    orphaned_in_sitemap: string[]
    seo_issues: Record<string, string[]>
    hygiene: SitemapHygiene | null
    verdict: "PASS" | "FAIL"
    exit_code: number
    warnings: string[]
}

// ── Sub-components ────────────────────────────────────────────────────────────

const StatCard: React.FC<{
    label: string
    value: number
    color: "emerald" | "amber" | "rose" | "zinc"
    icon: React.ReactNode
}> = ({ label, value, color, icon }) => {
    const colorMap = {
        emerald: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
        amber: "text-amber-400 bg-amber-400/10 border-amber-400/20",
        rose: "text-rose-400 bg-rose-400/10 border-rose-400/20",
        zinc: "text-zinc-400 bg-zinc-400/10 border-zinc-400/20",
    }
    return (
        <div className={cn("rounded-lg border p-4 flex items-center gap-4", colorMap[color])}>
            <div className="shrink-0">{icon}</div>
            <div>
                <p className="text-2xl font-bold font-mono">{value}</p>
                <p className="text-xs font-medium opacity-80">{label}</p>
            </div>
        </div>
    )
}

const ExpandableList: React.FC<{
    title: string
    items: string[]
    colorClass: string
    defaultOpen?: boolean
}> = ({ title, items, colorClass, defaultOpen = false }) => {
    const [open, setOpen] = useState(defaultOpen)
    if (items.length === 0) return null
    return (
        <div className="rounded-lg border border-zinc-700 overflow-hidden">
            <button
                onClick={() => setOpen(!open)}
                className="w-full flex items-center justify-between px-4 py-3 bg-zinc-800/50 hover:bg-zinc-800 transition-colors text-left"
            >
                <span className={cn("text-sm font-semibold", colorClass)}>
                    {title}
                    <span className="ml-2 font-mono text-xs bg-zinc-700 text-zinc-300 px-2 py-0.5 rounded-full">
                        {items.length}
                    </span>
                </span>
                {open ? (
                    <ChevronDown className="h-4 w-4 text-zinc-500" />
                ) : (
                    <ChevronRight className="h-4 w-4 text-zinc-500" />
                )}
            </button>
            {open && (
                <div className="divide-y divide-zinc-700/50 max-h-64 overflow-y-auto">
                    {items.map((item, i) => (
                        <div key={i} className="flex items-center gap-3 px-4 py-2 hover:bg-zinc-800/30 group">
                            <Link2 className="h-3 w-3 text-zinc-600 shrink-0" />
                            <a
                                href={item}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs text-blue-400 hover:text-blue-300 truncate flex-1"
                                title={item}
                            >
                                {item}
                            </a>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

const VerdictBadge: React.FC<{ verdict: "PASS" | "FAIL" }> = ({ verdict }) =>
    verdict === "PASS" ? (
        <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-emerald-400/10 border border-emerald-400/30">
            <CheckCircle2 className="h-5 w-5 text-emerald-400" />
            <span className="text-emerald-400 font-bold text-lg tracking-wide">PASS</span>
        </div>
    ) : (
        <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-rose-400/10 border border-rose-400/30">
            <XCircle className="h-5 w-5 text-rose-400" />
            <span className="text-rose-400 font-bold text-lg tracking-wide">FAIL</span>
        </div>
    )

const HygienePanel: React.FC<{ hygiene: SitemapHygiene }> = ({ hygiene }) => (
    <div className="rounded-lg border border-zinc-700 p-4 space-y-2">
        <h4 className="text-sm font-semibold text-zinc-300 mb-3 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-zinc-400" />
            Sitemap Hygiene
        </h4>
        <div className="grid grid-cols-2 gap-2 text-xs">
            {[
                ["Total URLs", hygiene.total_urls],
                ["Missing <lastmod>", hygiene.missing_lastmod],
                ["Duplicate <loc>", hygiene.duplicate_locs.length],
                ["Non-200 entries", Object.keys(hygiene.non_200_entries).length],
                ["Redirect entries", hygiene.redirect_entries.length],
                ["Over 50k limit", hygiene.over_url_limit ? "Yes ⚠" : "No"],
            ].map(([label, val]) => (
                <div key={String(label)} className="flex justify-between bg-zinc-800/50 rounded px-3 py-1.5">
                    <span className="text-zinc-500">{label}</span>
                    <span className={cn(
                        "font-mono font-medium",
                        (val === "Yes ⚠" || (typeof val === "number" && val > 0))
                            ? "text-amber-400"
                            : "text-zinc-300"
                    )}>
                        {String(val)}
                    </span>
                </div>
            ))}
        </div>
    </div>
)

// ── Main Panel ────────────────────────────────────────────────────────────────

export default function AuditPanel() {
    const [url, setUrl] = useState("")
    const [sitemapOverride, setSitemapOverride] = useState("")
    const [maxPages, setMaxPages] = useState(500)
    const [maxWorkers, setMaxWorkers] = useState(5)
    const [delay, setDelay] = useState(0.5)
    const [stripQuery, setStripQuery] = useState(false)
    const [jsFallback, setJsFallback] = useState(false)

    const [isRunning, setIsRunning] = useState(false)
    const [wsConnected, setWsConnected] = useState(false)
    const [logs, setLogs] = useState<string[]>([])
    const [report, setReport] = useState<AuditReport | null>(null)
    const [showReport, setShowReport] = useState(false)
    const [isLoadingReport, setIsLoadingReport] = useState(false)

    const scrollRef = useRef<HTMLDivElement>(null)
    const wsRef = useRef<WebSocket | null>(null)

    // Auto-scroll logs
    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }
    }, [logs])

    // WebSocket lifecycle
    useEffect(() => {
        const connect = () => {
            const ws = new WebSocket(getAuditWsUrl())
            wsRef.current = ws

            ws.onopen = () => {
                setWsConnected(true)
                setLogs(prev => [...prev, JSON.stringify({
                    timestamp: new Date().toISOString(), level: "SYSTEM",
                    message: "Connected to audit log stream",
                })])
            }
            ws.onmessage = (e) => setLogs(prev => [...prev, e.data])
            ws.onerror = () => {
                setWsConnected(false)
            }
            ws.onclose = () => {
                setWsConnected(false)
                // Reconnect after 3s if page is still mounted
                setTimeout(connect, 3000)
            }
        }
        connect()
        return () => wsRef.current?.close()
    }, [])

    // Status polling
    useEffect(() => {
        if (!isRunning) return
        const poll = async () => {
            try {
                const res = await fetch(`${API_BASE_URL}/audit/status`)
                if (!res.ok) return
                const data = await res.json()
                if (!data.is_running && isRunning) {
                    setIsRunning(false)
                    setLogs(prev => [...prev, JSON.stringify({
                        timestamp: new Date().toISOString(), level: "SYSTEM",
                        message: "Audit completed — click 'Load Report' to view results",
                    })])
                }
            } catch { /* ignore */ }
        }
        const id = setInterval(poll, 3000)
        return () => clearInterval(id)
    }, [isRunning])

    const handleStart = async () => {
        if (!url) return
        setLogs([])
        setReport(null)
        setShowReport(false)
        setIsRunning(true)
        try {
            const res = await fetch(`${API_BASE_URL}/audit`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    url,
                    sitemap_override: sitemapOverride,
                    max_pages: maxPages,
                    max_workers: maxWorkers,
                    delay,
                    strip_query: stripQuery,
                    js_fallback: jsFallback,
                }),
            })
            if (!res.ok) {
                const err = await res.json()
                throw new Error(err.detail || "Failed to start")
            }
        } catch (e) {
            console.error(e)
            setIsRunning(false)
            setLogs(prev => [...prev, JSON.stringify({
                timestamp: new Date().toISOString(), level: "ERROR",
                message: String(e),
            })])
        }
    }

    const handleStop = async () => {
        await fetch(`${API_BASE_URL}/audit/stop`, { method: "POST" }).catch(() => {})
        setIsRunning(false)
    }

    const handleLoadReport = async () => {
        setIsLoadingReport(true)
        try {
            const res = await fetch(`${API_BASE_URL}/audit/report`)
            if (!res.ok) throw new Error("No report available")
            const data: AuditReport = await res.json()
            setReport(data)
            setShowReport(true)
        } catch (e) {
            console.error(e)
            setLogs(prev => [...prev, JSON.stringify({
                timestamp: new Date().toISOString(), level: "ERROR",
                message: "Could not load report — run an audit first",
            })])
        } finally {
            setIsLoadingReport(false)
        }
    }

    const handleDownloadReport = () => {
        window.open(`${API_BASE_URL}/audit/report`, "_blank")
    }

    const parsedLogs = logs.map(l => {
        try { return JSON.parse(l) }
        catch { return { message: l, level: "RAW", timestamp: new Date().toISOString() } }
    })

    return (
        <div className="grid lg:grid-cols-12 gap-8">
            {/* Left: Config */}
            <div className="lg:col-span-4 space-y-4">
                <Card className="border-2 shadow-sm">
                    <CardHeader className="pb-4">
                        <CardTitle className="flex items-center gap-2">
                            <FileSearch className="h-5 w-5" />
                            Sitemap Audit
                        </CardTitle>
                        <CardDescription>
                            Cross-reference crawled pages against the XML sitemap.
                        </CardDescription>
                    </CardHeader>

                    <CardContent className="space-y-4">
                        <div className="space-y-1.5">
                            <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Target URL</label>
                            <div className="relative group">
                                <Globe className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                                <Input
                                    placeholder="https://example.com"
                                    className="pl-9 h-10 bg-muted/30"
                                    value={url}
                                    onChange={e => setUrl(e.target.value)}
                                />
                            </div>
                        </div>

                        <div className="space-y-1.5">
                            <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                Sitemap Override <span className="normal-case font-normal">(optional)</span>
                            </label>
                            <Input
                                placeholder="https://example.com/custom-sitemap.xml"
                                className="h-10 bg-muted/30 text-xs"
                                value={sitemapOverride}
                                onChange={e => setSitemapOverride(e.target.value)}
                            />
                        </div>

                        <div className="grid grid-cols-2 gap-3">
                            <div className="space-y-1.5">
                                <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Max Pages</label>
                                <Input
                                    type="number" min={10} max={5000} step={10}
                                    className="h-9 bg-muted/30 text-sm"
                                    value={maxPages}
                                    onChange={e => setMaxPages(parseInt(e.target.value) || 500)}
                                />
                            </div>
                            <div className="space-y-1.5">
                                <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Workers</label>
                                <Input
                                    type="number" min={1} max={20}
                                    className="h-9 bg-muted/30 text-sm"
                                    value={maxWorkers}
                                    onChange={e => setMaxWorkers(parseInt(e.target.value) || 5)}
                                />
                            </div>
                            <div className="space-y-1.5">
                                <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Delay (s)</label>
                                <Input
                                    type="number" min={0} max={5} step={0.1}
                                    className="h-9 bg-muted/30 text-sm"
                                    value={delay}
                                    onChange={e => setDelay(parseFloat(e.target.value) || 0.5)}
                                />
                            </div>
                        </div>

                        <div className="flex flex-col gap-2 pt-1">
                            <label className="flex items-center gap-3 cursor-pointer group">
                                <input
                                    type="checkbox"
                                    checked={stripQuery}
                                    onChange={e => setStripQuery(e.target.checked)}
                                    className="h-4 w-4 rounded accent-emerald-500"
                                />
                                <span className="text-xs text-muted-foreground group-hover:text-foreground transition-colors">
                                    Strip query strings from URLs
                                </span>
                            </label>
                            <label className="flex items-center gap-3 cursor-pointer group">
                                <input
                                    type="checkbox"
                                    checked={jsFallback}
                                    onChange={e => setJsFallback(e.target.checked)}
                                    className="h-4 w-4 rounded accent-emerald-500"
                                />
                                <span className="text-xs text-muted-foreground group-hover:text-foreground transition-colors">
                                    JS fallback (Selenium) for SPAs
                                </span>
                            </label>
                        </div>
                    </CardContent>

                    <CardFooter className="flex flex-col gap-2 pt-2">
                        {!isRunning ? (
                            <Button className="w-full h-10 font-semibold" onClick={handleStart} disabled={!url}>
                                <Play className="mr-2 h-4 w-4 fill-current" /> Run Audit
                            </Button>
                        ) : (
                            <Button variant="destructive" className="w-full h-10 font-semibold" onClick={handleStop}>
                                <Square className="mr-2 h-4 w-4 fill-current" /> Stop Audit
                            </Button>
                        )}
                        <Button
                            variant="outline" className="w-full h-10"
                            onClick={handleLoadReport}
                            disabled={isRunning || isLoadingReport}
                        >
                            <FileSearch className="mr-2 h-4 w-4" />
                            {isLoadingReport ? "Loading…" : "Load Report"}
                        </Button>
                        <Button
                            variant="secondary" className="w-full h-10"
                            onClick={handleDownloadReport}
                            disabled={isRunning}
                        >
                            <Download className="mr-2 h-4 w-4" /> Download JSON
                        </Button>
                    </CardFooter>
                </Card>

                {/* Connection status */}
                <Card className="bg-muted/10 border-dashed">
                    <CardContent className="p-4 flex items-center justify-between text-sm text-muted-foreground">
                        <span>Audit stream</span>
                        <div className="flex items-center gap-2">
                            <div className={cn("h-2 w-2 rounded-full", wsConnected ? "bg-emerald-500 animate-pulse" : "bg-zinc-600")} />
                            <span className="text-xs">{wsConnected ? "Connected" : "Disconnected"}</span>
                        </div>
                    </CardContent>
                </Card>
            </div>

            {/* Right: Logs + Report */}
            <div className="lg:col-span-8 space-y-6">
                {/* Live log terminal */}
                <Card className="border-2 shadow-sm overflow-hidden bg-zinc-950 text-zinc-50 h-72 flex flex-col">
                    <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-900">
                        <div className="flex items-center gap-2">
                            <Terminal className="h-4 w-4 text-zinc-400" />
                            <span className="text-sm font-medium text-zinc-300">Audit Log</span>
                        </div>
                        <div className="flex gap-1.5">
                            <div className="h-3 w-3 rounded-full bg-red-500/20 border border-red-500/50" />
                            <div className="h-3 w-3 rounded-full bg-yellow-500/20 border border-yellow-500/50" />
                            <div className="h-3 w-3 rounded-full bg-green-500/20 border border-green-500/50" />
                        </div>
                    </div>
                    <div
                        ref={scrollRef}
                        className="flex-1 overflow-y-auto p-4 font-mono text-xs space-y-1"
                    >
                        {parsedLogs.length === 0 && (
                            <div className="h-full flex flex-col items-center justify-center text-zinc-600 space-y-2">
                                <Activity className="h-8 w-8 opacity-50" />
                                <p>Configure and run an audit to begin…</p>
                            </div>
                        )}
                        {parsedLogs.map((log, i) => (
                            <div key={i} className={cn(
                                "flex gap-4 py-0.5 border-b border-white/5 items-start",
                                log.level === "ERROR" && "text-red-300",
                            )}>
                                <span className="shrink-0 w-[85px] text-zinc-500">
                                    {new Date(log.timestamp).toLocaleTimeString("en-GB", { hour12: false })}
                                </span>
                                <span className={cn(
                                    "shrink-0 w-[60px] font-bold",
                                    log.level === "ERROR" && "text-red-500",
                                    log.level === "WARNING" && "text-amber-500",
                                    log.level === "INFO" && "text-emerald-500",
                                    log.level === "SYSTEM" && "text-blue-400",
                                    !["ERROR", "WARNING", "INFO", "SYSTEM"].includes(log.level) && "text-zinc-500",
                                )}>
                                    {log.level}
                                </span>
                                <span className="flex-1 break-all text-zinc-300">{log.message}</span>
                            </div>
                        ))}
                    </div>
                </Card>

                {/* Report panel */}
                {showReport && report && (
                    <div className="space-y-4">
                        {/* Verdict + warnings */}
                        <div className="flex items-center justify-between flex-wrap gap-3">
                            <VerdictBadge verdict={report.verdict} />
                            <span className="text-xs text-zinc-500 font-mono">
                                {report.root_url}
                            </span>
                        </div>

                        {report.warnings.length > 0 && (
                            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 space-y-1">
                                {report.warnings.map((w, i) => (
                                    <div key={i} className="flex items-start gap-2 text-xs text-amber-300">
                                        <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                                        <span>{w}</span>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Coverage stats */}
                        <div className="grid grid-cols-3 gap-3">
                            <StatCard
                                label="Covered"
                                value={report.covered.length}
                                color="emerald"
                                icon={<CheckCircle2 className="h-6 w-6" />}
                            />
                            <StatCard
                                label="Missing from Sitemap"
                                value={report.missing_from_sitemap.length}
                                color="amber"
                                icon={<AlertTriangle className="h-6 w-6" />}
                            />
                            <StatCard
                                label="Orphaned in Sitemap"
                                value={report.orphaned_in_sitemap.length}
                                color={report.orphaned_in_sitemap.length > 0 ? "rose" : "zinc"}
                                icon={<XCircle className="h-6 w-6" />}
                            />
                        </div>

                        {/* Gap tables */}
                        <div className="space-y-2">
                            <ExpandableList
                                title="Missing from Sitemap"
                                items={report.missing_from_sitemap}
                                colorClass="text-amber-400"
                                defaultOpen={report.missing_from_sitemap.length > 0}
                            />
                            <ExpandableList
                                title="Orphaned in Sitemap (non-200 / unreachable)"
                                items={report.orphaned_in_sitemap}
                                colorClass="text-rose-400"
                                defaultOpen={report.orphaned_in_sitemap.length > 0}
                            />
                        </div>

                        {/* SEO issues */}
                        {Object.keys(report.seo_issues).length > 0 && (
                            <div className="space-y-2">
                                <h4 className="text-sm font-semibold text-zinc-300 flex items-center gap-2">
                                    <Info className="h-4 w-4 text-zinc-400" />
                                    SEO Issues
                                </h4>
                                {Object.entries(report.seo_issues).map(([key, urls]) => (
                                    <ExpandableList
                                        key={key}
                                        title={key.replace(/_/g, " ")}
                                        items={urls}
                                        colorClass="text-purple-400"
                                        defaultOpen
                                    />
                                ))}
                            </div>
                        )}

                        {/* Hygiene */}
                        {report.hygiene && <HygienePanel hygiene={report.hygiene} />}
                    </div>
                )}
            </div>
        </div>
    )
}

import React, { useState, useEffect, useRef } from 'react';
import { 
  Play, Pause, RotateCcw, StopCircle, HelpCircle, 
  Settings, MessageSquare, Send, Globe, 
  Terminal, ShieldAlert, Activity, 
  Layers, ChevronRight, Key, Info
} from 'lucide-react';

interface Stats {
  status: string;
  start_url: string;
  pages_completed: number;
  pages_discovered: number;
  pages_remaining: number;
  speed_ppm: number;
  eta_mins: number;
  memory_usage_mb: number;
  chunks_count: number;
  current_url: string;
  current_section: string;
  screenshot?: string;
}

interface LogLine {
  id: number;
  timestamp: string;
  level: string;
  message: string;
}

interface SitemapNode {
  url: string;
  title: string;
  status: string;
}


interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  sources?: Array<{
    title: string;
    headings: string;
    url: string;
    similarity: number;
  }>;
}

export default function App() {
  // Stats & State
  const [stats, setStats] = useState<Stats>({
    status: 'idle',
    start_url: '',
    pages_completed: 0,
    pages_discovered: 0,
    pages_remaining: 0,
    speed_ppm: 0,
    eta_mins: 0,
    memory_usage_mb: 0,
    chunks_count: 0,
    current_url: '',
    current_section: ''
  });

  // Settings
  const [startUrl, setStartUrl] = useState('https://nodejs.org/docs/latest/api/');
  const [cdpUrl, setCdpUrl] = useState('');
  const [ollamaUrl, setOllamaUrl] = useState('http://localhost:11434');
  const [llmModel, setLlmModel] = useState('llama3');
  const [embeddingModel, setEmbeddingModel] = useState('nomic-embed-text');
  const [ollamaModelsList, setOllamaModelsList] = useState<string[]>([]);
  const [showSettings, setShowSettings] = useState(false);

  // Components lists
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [sitemapPages, setSitemapPages] = useState<SitemapNode[]>([]);
  
  // Chat
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [chatLoading, setChatLoading] = useState(false);

  // References
  const wsRef = useRef<WebSocket | null>(null);
  const logScrollRef = useRef<HTMLDivElement>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);

  // 1. WebSocket connection for real-time progress
  useEffect(() => {
    connectWebSocket();
    fetchSettings();
    fetchLogs();
    fetchSitemap();
    fetchChatHistory();

    const interval = setInterval(() => {
      // Periodic fetch for logs and sitemap when actively crawling
      if (stats.status === 'crawling' || stats.status === 'mapping') {
        fetchLogs();
        fetchSitemap();
      }
    }, 3000);

    return () => {
      clearInterval(interval);
      if (wsRef.current) wsRef.current.close();
    };
  }, [stats.status]);

  // Autoscroll logs and chat
  useEffect(() => {
    if (logScrollRef.current) {
      logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight;
    }
  }, [logs]);

  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    }
  }, [chatHistory, chatLoading]);

  const connectWebSocket = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws/progress`;

    console.log(`Connecting to WebSocket: ${wsUrl}`);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'progress') {
        setStats(msg.data);
      }
    };

    ws.onerror = (err) => {
      console.error('WebSocket encountered error:', err);
    };

    ws.onclose = () => {
      console.log('WebSocket closed. Reconnecting in 3s...');
      setTimeout(connectWebSocket, 3000);
    };
  };

  // 2. Fetch configurations
  const fetchOllamaModels = async () => {
    try {
      const res = await fetch('/api/ollama/models');
      const data = await res.json();
      if (data.models) {
        setOllamaModelsList(data.models);
      }
    } catch (err) {
      console.error('Error fetching Ollama models:', err);
    }
  };

  const fetchSettings = async () => {
    try {
      const res = await fetch('/api/settings');
      const data = await res.json();
      setOllamaUrl(data.ollama_url || 'http://localhost:11434');
      setLlmModel(data.llm_model || 'llama3');
      setEmbeddingModel(data.embedding_model || 'nomic-embed-text');
      if (data.start_url) setStartUrl(data.start_url);
      
      // Fetch models list
      fetchOllamaModels();
    } catch (err) {
      console.error('Error fetching settings:', err);
    }
  };

  const saveSettings = async () => {
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ollama_url: ollamaUrl,
          llm_model: llmModel,
          embedding_model: embeddingModel
        })
      });
      if (res.ok) {
        alert('Settings saved successfully!');
        setShowSettings(false);
      }
    } catch (err) {
      console.error('Error saving settings:', err);
    }
  };

  const fetchLogs = async () => {
    try {
      const res = await fetch('/api/logs');
      const data = await res.json();
      setLogs(data.reverse()); // Latest logs at the bottom
    } catch (err) {
      console.error('Error fetching logs:', err);
    }
  };

  const fetchSitemap = async () => {
    try {
      const res = await fetch('/api/sitemap');
      const data = await res.json();
      setSitemapPages(data.pages || []);
    } catch (err) {
      console.error('Error fetching sitemap:', err);
    }
  };

  const fetchChatHistory = async () => {
    try {
      const res = await fetch('/api/chat/history');
      const data = await res.json();
      setChatHistory(data || []);
    } catch (err) {
      console.error('Error fetching chat history:', err);
    }
  };

  // 3. Crawler controls
  const handleStart = async () => {
    try {
      setLogs([]);
      setSitemapPages([]);
      setChatHistory([]);
      const res = await fetch('/api/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: startUrl,
          cdp_url: cdpUrl || null
        })
      });
      if (!res.ok) {
        const data = await res.json();
        alert(`Error starting crawler: ${data.detail}`);
      }
    } catch (err) {
      console.error('Error starting crawl:', err);
    }
  };

  const handleControl = async (action: string) => {
    try {
      await fetch('/api/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
      });
      fetchLogs();
      fetchSitemap();
    } catch (err) {
      console.error(`Error sending control action ${action}:`, err);
    }
  };

  // 4. Chat queries
  const handleSendChat = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim() || chatLoading) return;

    const queryMsg = chatInput.trim();
    setChatInput('');
    setChatLoading(true);

    // Append user message immediately
    const userBubble: ChatMessage = {
      role: 'user',
      content: queryMsg,
      timestamp: new Date().toISOString()
    };
    setChatHistory(prev => [...prev, userBubble]);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: queryMsg })
      });
      
      const data = await res.json();
      
      const assistantBubble: ChatMessage = {
        role: 'assistant',
        content: data.response,
        timestamp: new Date().toISOString(),
        sources: data.sources
      };
      
      setChatHistory(prev => [...prev, assistantBubble]);
    } catch (err) {
      console.error('Error querying chatbot:', err);
      const errBubble: ChatMessage = {
        role: 'assistant',
        content: `Error occurred: ${err}`,
        timestamp: new Date().toISOString()
      };
      setChatHistory(prev => [...prev, errBubble]);
    } finally {
      setChatLoading(false);
    }
  };

  const handleClearChat = async () => {
    try {
      const res = await fetch('/api/chat/clear', { method: 'POST' });
      if (res.ok) {
        setChatHistory([]);
      }
    } catch (err) {
      console.error('Error clearing chat:', err);
    }
  };

  // Progress percentage calculation
  const progressPercent = stats.pages_discovered > 0
    ? Math.round((stats.pages_completed / stats.pages_discovered) * 100)
    : 0;

  return (
    <div className="app-container">
      {/* 1. LEFT SIDEBAR: CONFIG & CONTROLS */}
      <aside className="sidebar-controls">
        {/* Brand Header */}
        <div className="glass-panel" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{ padding: '8px', background: 'var(--gradient-primary)', borderRadius: '10px' }}>
            <Activity size={20} color="#fff" />
          </div>
          <div>
            <h2 style={{ fontSize: '16px', fontWeight: 700, margin: 0 }}>WebIntel</h2>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Website Learning Assistant</span>
          </div>
        </div>

        {/* Configurations Card */}
        <div className="glass-panel" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ fontSize: '13px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Crawl Setup</h3>
            <button className="btn btn-secondary" style={{ padding: '6px' }} onClick={() => setShowSettings(!showSettings)}>
              <Settings size={14} />
            </button>
          </div>

          {!showSettings ? (
            <>
              <div>
                <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Target Documentation URL</label>
                <input 
                  type="text" 
                  className="input-field" 
                  value={startUrl} 
                  disabled={stats.status !== 'idle' && stats.status !== 'stopped'}
                  onChange={e => setStartUrl(e.target.value)} 
                  placeholder="https://example.com/docs/"
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Attach CDP Port (Optional)</label>
                <input 
                  type="text" 
                  className="input-field" 
                  value={cdpUrl} 
                  disabled={stats.status !== 'idle' && stats.status !== 'stopped'}
                  onChange={e => setCdpUrl(e.target.value)} 
                  placeholder="http://localhost:9222"
                />
              </div>
            </>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', background: 'rgba(255,255,255,0.02)', padding: '10px', borderRadius: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 600, color: 'var(--accent-purple)' }}>
                <Key size={14} /> Local AI Configuration (Ollama)
              </div>

              <div>
                <label style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'block', marginBottom: '2px' }}>Ollama Host URL</label>
                <input 
                  type="text" 
                  className="input-field" 
                  value={ollamaUrl} 
                  onChange={e => setOllamaUrl(e.target.value)} 
                  placeholder="http://localhost:11434"
                />
              </div>

              <div>
                <label style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'block', marginBottom: '2px' }}>LLM Chat Model</label>
                <select 
                  className="input-field" 
                  value={llmModel} 
                  onChange={e => setLlmModel(e.target.value)}
                  style={{ appearance: 'none', background: 'black' }}
                >
                  {ollamaModelsList.length === 0 ? (
                    <option value="llama3">llama3 (Default)</option>
                  ) : (
                    ollamaModelsList.map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))
                  )}
                </select>
              </div>

              <div>
                <label style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'block', marginBottom: '2px' }}>Embedding Model</label>
                <select 
                  className="input-field" 
                  value={embeddingModel} 
                  onChange={e => setEmbeddingModel(e.target.value)}
                  style={{ appearance: 'none', background: 'black' }}
                >
                  {ollamaModelsList.length === 0 ? (
                    <option value="nomic-embed-text">nomic-embed-text (Default)</option>
                  ) : (
                    ollamaModelsList.map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))
                  )}
                </select>
              </div>

              <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
                <button className="btn btn-primary" style={{ flex: 1, fontSize: '12px', padding: '6px 12px' }} onClick={saveSettings}>Save</button>
                <button className="btn btn-secondary" style={{ flex: 1, fontSize: '12px', padding: '6px 12px' }} onClick={() => setShowSettings(false)}>Cancel</button>
              </div>
            </div>
          )}

          {/* Action buttons */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '6px' }}>
            {(stats.status === 'idle' || stats.status === 'stopped') && (
              <button className="btn btn-primary" style={{ gridColumn: 'span 2' }} onClick={handleStart}>
                <Play size={16} /> Start Learning
              </button>
            )}

            {(stats.status === 'crawling' || stats.status === 'mapping') && (
              <>
                <button className="btn btn-secondary" onClick={() => handleControl('pause')}>
                  <Pause size={16} /> Pause
                </button>
                <button className="btn btn-danger" onClick={() => handleControl('stop')}>
                  <StopCircle size={16} /> Stop
                </button>
              </>
            )}

            {stats.status === 'paused' && (
              <>
                <button className="btn btn-primary" onClick={() => handleControl('resume')}>
                  <Play size={16} /> Resume
                </button>
                <button className="btn btn-danger" onClick={() => handleControl('stop')}>
                  <StopCircle size={16} /> Stop
                </button>
              </>
            )}
          </div>

          <button 
            className="btn btn-secondary" 
            style={{ width: '100%', borderColor: 'rgba(244, 63, 94, 0.3)', color: 'var(--accent-red)' }} 
            onClick={() => handleControl('reset')}
            disabled={stats.status === 'crawling' || stats.status === 'mapping'}
          >
            <RotateCcw size={14} /> Clear SQLite & Vector DB
          </button>
        </div>

        {/* Emergency Stop Panel */}
        <div className="glass-panel" style={{ padding: '16px', background: 'rgba(244, 63, 94, 0.04)', border: '1px solid rgba(244, 63, 94, 0.2)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--accent-red)', fontWeight: 600, fontSize: '13px' }}>
            <ShieldAlert size={16} />
            <span>Emergency Interrupts</span>
          </div>
          <p style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
            Press global hotkey <code style={{ color: 'var(--accent-red)', padding: '2px 4px', background: 'rgba(244,63,94,0.1)', borderRadius: '4px', fontFamily: 'monospace' }}>Ctrl + Alt + Q</code> or slam mouse into top-left corner (0,0) to instantly kill Playwright browser.
          </p>
          <button 
            className="btn btn-danger" 
            style={{ width: '100%', padding: '12px', background: 'linear-gradient(135deg, #f43f5e 0%, #e11d48 100%)', boxShadow: '0 0 10px rgba(244, 63, 94, 0.2)' }}
            disabled={stats.status === 'idle' || stats.status === 'stopped'}
            onClick={() => handleControl('stop')}
          >
            EMERGENCY STOP
          </button>
        </div>

      </aside>

      {/* 2. CENTER PANEL: PROGRESS, STATS, SITEMAP */}
      <main className="center-viewport">
        {/* Current status bar */}
        <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span className={`status-indicator ${stats.status}`} />
            <div>
              <h2 style={{ fontSize: '15px', textTransform: 'capitalize', fontWeight: 700 }}>
                {stats.status === 'idle' ? 'Ready to Learn' : stats.status === 'mapping' ? 'Scanning Site Structure...' : stats.status === 'crawling' ? 'Learning Web Content...' : stats.status === 'paused' ? 'Crawling Paused' : 'Crawling Stopped'}
              </h2>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                {stats.current_url ? stats.current_url : 'No active website.'}
              </span>
            </div>
          </div>
          
          {stats.status !== 'idle' && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
              <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--accent-purple)' }}>{progressPercent}% Complete</span>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{stats.pages_completed} / {stats.pages_discovered} pages</span>
            </div>
          )}
        </div>

        {/* Metrics Grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
          <div className="glass-panel" style={{ padding: '12px 16px' }}>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'block', textTransform: 'uppercase' }}>Pages Completed</span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', marginTop: '4px' }}>
              <span style={{ fontSize: '20px', fontWeight: 700 }}>{stats.pages_completed}</span>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>crawled</span>
            </div>
          </div>

          <div className="glass-panel" style={{ padding: '12px 16px' }}>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'block', textTransform: 'uppercase' }}>Remaining Queue</span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', marginTop: '4px' }}>
              <span style={{ fontSize: '20px', fontWeight: 700, color: stats.pages_remaining > 0 ? 'var(--accent-indigo)' : 'inherit' }}>{stats.pages_remaining}</span>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>pending</span>
            </div>
          </div>

          <div className="glass-panel" style={{ padding: '12px 16px' }}>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'block', textTransform: 'uppercase' }}>Knowledge Base</span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', marginTop: '4px' }}>
              <span style={{ fontSize: '20px', fontWeight: 700, color: 'var(--accent-purple)' }}>{stats.chunks_count}</span>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>chunks</span>
            </div>
          </div>

          <div className="glass-panel" style={{ padding: '12px 16px' }}>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'block', textTransform: 'uppercase' }}>Crawl Speed</span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', marginTop: '4px' }}>
              <span style={{ fontSize: '20px', fontWeight: 700 }}>{stats.speed_ppm}</span>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>pages/m</span>
            </div>
          </div>
        </div>

        {/* Progress Bar & Current Section */}
        {stats.status !== 'idle' && (
          <div className="glass-panel" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Layers size={12} /> CURRENT SECTION
              </span>
              <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>{stats.current_section || 'Scanning...'}</span>
            </div>
            <div className="progress-bar-container">
              <div className="progress-bar-fill" style={{ width: `${progressPercent}%` }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-muted)' }}>
              <span>ETA: {stats.eta_mins} mins</span>
              <span>Memory: {stats.memory_usage_mb} MB</span>
            </div>
          </div>
        )}

        {/* Sitemap Visualizer & Live Preview Panel Row */}
        <div style={{ flex: 1, display: 'flex', gap: '16px', minHeight: 0 }}>
          {/* Sitemap Tree Panel */}
          <div className="glass-panel" style={{ flex: 1.2, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
            <div style={{ padding: '16px', borderBottom: '1px solid var(--border-glass)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Globe size={16} color="var(--accent-indigo)" />
              <h3 style={{ fontSize: '14px', fontWeight: 600 }}>Web Sitemap Map Hierarchy</h3>
            </div>
            <div className="sitemap-visualizer" style={{ overflowY: 'auto', padding: '16px', display: 'block', height: '100%', width: '100%' }}>
              {sitemapPages.length === 0 ? (
                <div style={{ color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center', marginTop: '40px' }}>
                  <Info size={32} style={{ opacity: 0.3, marginBottom: '8px' }} />
                  <p>Website map is empty.</p>
                  <p style={{ fontSize: '11px', marginTop: '4px' }}>Start the learning process to build and explore the site-map tree.</p>
                </div>
              ) : (
                <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {sitemapPages.map((page) => {
                    const relativeUrl = page.url.replace(stats.start_url || '', '');
                    const displayLabel = page.title ? page.title : relativeUrl || '/';
                    
                    return (
                      <div 
                        key={page.url} 
                        style={{ 
                          display: 'flex', 
                          alignItems: 'center', 
                          gap: '8px', 
                          padding: '6px 12px', 
                          background: page.status === 'crawled' ? 'rgba(16, 185, 129, 0.04)' : page.status === 'crawling' ? 'rgba(59, 130, 246, 0.08)' : 'rgba(255,255,255,0.01)',
                          border: '1px solid',
                          borderColor: page.status === 'crawled' ? 'rgba(16, 185, 129, 0.15)' : page.status === 'crawling' ? 'rgba(59, 130, 246, 0.3)' : 'var(--border-glass)',
                          borderRadius: '8px',
                          fontSize: '12px'
                        }}
                      >
                        <span className={`status-indicator ${page.status}`} style={{ margin: 0 }} />
                        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}>
                          <span style={{ fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{displayLabel}</span>
                          <a href={page.url} target="_blank" rel="noreferrer" style={{ fontSize: '10px', color: 'var(--text-muted)', textDecoration: 'none', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{page.url}</a>
                        </div>
                        <ChevronRight size={14} color="var(--text-muted)" />
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* Live Browser Preview Panel */}
          <div className="glass-panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
            <div style={{ padding: '16px', borderBottom: '1px solid var(--border-glass)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Globe size={16} color="var(--accent-green)" />
              <h3 style={{ fontSize: '14px', fontWeight: 600 }}>Live Assistant Browser View</h3>
            </div>
            <div style={{ flex: 1, padding: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.2)', minHeight: 0 }}>
              {stats.screenshot ? (
                <img 
                  src={`data:image/jpeg;base64,${stats.screenshot}`} 
                  alt="Live Browser View" 
                  style={{ width: '100%', height: 'auto', maxHeight: '100%', objectFit: 'contain', borderRadius: '8px', border: '1px solid var(--border-glass)' }} 
                />
              ) : (
                <div style={{ color: 'var(--text-muted)', fontSize: '12px', textAlign: 'center' }}>
                  <Globe size={32} style={{ opacity: 0.2, marginBottom: '8px' }} />
                  <p>Browser inactive.</p>
                  <p style={{ fontSize: '10px', marginTop: '4px' }}>Start learning to stream live assistant browser view.</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Bottom Panel: System Logs Console */}
        <div className="glass-panel" style={{ height: '220px', display: 'flex', flexDirection: 'column', gap: '8px', padding: '16px', overflow: 'hidden', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Terminal size={14} color="var(--text-muted)" />
            <h3 style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>System Logs</h3>
          </div>
          <div 
            ref={logScrollRef}
            style={{ flex: 1, overflowY: 'auto', background: 'black', borderRadius: '8px', padding: '10px', border: '1px solid var(--border-glass)' }}
          >
            {logs.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '11px', fontFamily: 'monospace' }}>System idle. Waiting for logs...</div>
            ) : (
              logs.map((log) => (
                <div key={log.id} className={`log-line ${log.level}`}>
                  [{log.timestamp.split('T')[1].substring(0, 8)}] {log.message}
                </div>
              ))
            )}
          </div>
        </div>
      </main>

      {/* 3. RIGHT PANEL: CHAT WINDOW */}
      <section className="glass-panel chat-viewport">
        {/* Chat Panel Header */}
        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-glass)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <MessageSquare size={16} color="var(--accent-purple)" />
            <div>
              <h3 style={{ fontSize: '14px', fontWeight: 600 }}>Ask Documentation Assistant</h3>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Answers strictly based on gathered knowledge</span>
            </div>
          </div>
          {chatHistory.length > 0 && (
            <button 
              className="btn btn-secondary" 
              style={{ padding: '6px 10px', fontSize: '11px', borderColor: 'rgba(244, 63, 94, 0.2)', color: 'var(--accent-red)' }} 
              onClick={handleClearChat}
            >
              Clear Chat
            </button>
          )}
        </div>

        {/* Chat History Messages */}
        <div ref={chatScrollRef} className="chat-messages">
          {chatHistory.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center', margin: 'auto 0', padding: '24px' }}>
              <HelpCircle size={40} style={{ opacity: 0.2, margin: '0 auto 12px auto' }} />
              <p style={{ fontWeight: 600 }}>Ask your documentation!</p>
              <p style={{ fontSize: '11px', marginTop: '6px', color: 'var(--text-muted)' }}>
                "Compare streams and buffers."<br/>
                "How does the file system API work?"
              </p>
            </div>
          ) : (
            chatHistory.map((msg, index) => (
              <div key={index} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <div className={`message-bubble ${msg.role}`}>
                  {/* Markdown or plain-text response */}
                  <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                </div>
                
                {/* Matched Sources Cards for Assistant message */}
                {msg.role === 'assistant' && msg.sources && msg.sources.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', paddingLeft: '8px', marginBottom: '8px' }}>
                    <span style={{ fontSize: '9px', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 700 }}>Retrieved Sources:</span>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                      {msg.sources.slice(0, 3).map((src, sIdx) => (
                        <a 
                          key={sIdx} 
                          href={src.url} 
                          target="_blank" 
                          rel="noreferrer"
                          title={`Section: ${src.headings}`}
                          style={{ 
                            fontSize: '10px', 
                            background: 'rgba(255,255,255,0.03)', 
                            border: '1px solid var(--border-glass)', 
                            padding: '4px 8px', 
                            borderRadius: '6px', 
                            color: 'var(--accent-indigo)', 
                            textDecoration: 'none', 
                            whiteSpace: 'nowrap', 
                            maxWidth: '120px', 
                            overflow: 'hidden', 
                            textOverflow: 'ellipsis' 
                          }}
                        >
                          {src.title}
                        </a>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))
          )}
          
          {chatLoading && (
            <div className="message-bubble assistant" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <span className="status-indicator crawling" style={{ margin: 0 }} />
              <span style={{ color: 'var(--text-secondary)' }}>Searching vector database...</span>
            </div>
          )}
        </div>

        {/* Chat input box */}
        <form onSubmit={handleSendChat} style={{ padding: '16px', borderTop: '1px solid var(--border-glass)', display: 'flex', gap: '8px' }}>
          <input 
            type="text" 
            className="input-field" 
            value={chatInput} 
            onChange={e => setChatInput(e.target.value)} 
            disabled={chatLoading}
            placeholder="Ask a question..."
          />
          <button 
            type="submit" 
            className="btn btn-primary" 
            style={{ padding: '10px' }}
            disabled={!chatInput.trim() || chatLoading}
          >
            <Send size={16} />
          </button>
        </form>
      </section>
    </div>
  );
}

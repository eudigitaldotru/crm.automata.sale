import express from 'express';
import { execFile, spawn } from 'child_process';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const port = 5002;

app.use(express.json());

app.post('/api/refresh', (req, res) => {
    console.log('🔄 Received refresh request. Running extraction script...');
    
    // Path to the python script (one level up from dashboard/server.js)
    const scriptPath = path.join(__dirname, '..', 'scripts', 'extract_dashboard_data.py');
    
    execFile('python3', [scriptPath], { shell: false }, (error, stdout, stderr) => {
        if (error) {
            console.error(`❌ Error executing script: ${error.message}`);
            return res.status(500).json({ error: error.message });
        }
        if (stderr) {
            console.warn(`⚠️ Script stderr: ${stderr}`);
        }
        console.log(`✅ Extraction successful:\n${stdout}`);
        res.json({ message: 'Extraction successful', output: stdout });
    });
});

app.post('/api/refresh-monitoring', (req, res) => {
    console.log('🔄 Received monitoring refresh request...');
    const scriptPath = path.join(__dirname, '..', 'scripts', 'uptime_check.py');

    execFile('python3', [scriptPath], { shell: false }, (error, stdout, stderr) => {
        if (error) {
            console.error(`❌ Error executing monitoring script: ${error.message}`);
            return res.status(500).json({ error: error.message });
        }
        console.log(`✅ Monitoring refresh successful`);
        res.json({ message: 'Monitoring refreshed successful' });
    });
});

app.post('/api/refresh-geo', (req, res) => {
    console.log('🔍 Received GEO audit refresh request...');
    const scriptPath = path.join(__dirname, '..', 'scripts', 'geo_audit.py');

    execFile('python3', [scriptPath, '--refresh'], { shell: false }, (error, stdout, stderr) => {
        if (error) {
            console.error(`❌ Error executing GEO audit script: ${error.message}`);
            return res.status(500).json({ error: error.message });
        }
        console.log(`✅ GEO audit refresh successful:\n${stdout}`);
        res.json({ message: 'GEO audit refreshed successfully', output: stdout });
    });
});

app.post('/api/sync-tasks', (req, res) => {
    console.log('🔄 Received Task Sync request...');
    const scriptsDir = path.join(__dirname, '..', 'scripts');
    
    // Sequential execution: Reconcile Payments -> Check Statuses -> Reconcile -> Extract Data
    // reconcile_payments.py сверяет оплаты по банковской выписке Точки (get_statement),
    // т.к. API /bills/{id} Точки не работает (501) — единственный надёжный путь.
    const steps = [
        ['reconcile_payments.py', ['--apply', '--days', '35']],
        ['check_statuses.py', []],
        ['reconcile.py', []],
        ['extract_dashboard_data.py', []],
    ];
    const runSteps = (i, acc) => {
        if (i >= steps.length) return syncDone(null, acc);
        const [script, args] = steps[i];
        execFile('python3', [path.join(scriptsDir, script), ...args], { shell: false },
            (error, stdout, stderr) => {
                if (error) return syncDone(error, acc);
                runSteps(i + 1, acc + stdout);
            });
    };
    const syncDone = (error, stdout) => {
        if (error) {
            console.error(`❌ Sync failed: ${error.message}`);
            return res.status(500).json({ error: error.message });
        }
        console.log('✅ Task Sync successful');
        res.json({ message: 'Sync successful', output: stdout });
    };
    runSteps(0, '');
});

app.post('/api/start-service', (req, res) => {
    const { service } = req.body;
    const scriptsDir = path.join(__dirname, '..', 'scripts');
    let scriptName = '';
    let isDetached = false;

    if (service === 'tg_listener') {
        scriptName = 'tg_listener.py';
        isDetached = true; // TG Listener should stay alive
    } else if (service === 'overtime') {
        scriptName = 'reconcile_overtime.py';
        isDetached = false; // Overtime is a one-off
    } else {
        return res.status(400).json({ error: 'Unknown service' });
    }

    console.log(`🚀 Starting service: ${service} (${scriptName})...`);

    if (isDetached) {
        // Run as detached process (useful for persistent listeners)
        const child = spawn('python3', [scriptName], {
            cwd: scriptsDir,
            detached: true,
            stdio: 'ignore'
        });
        child.unref();
        res.json({ message: `Service ${service} started in background` });
    } else {
        // Run and wait (for one-off scripts)
        execFile('python3', [path.join(scriptsDir, scriptName)], { shell: false }, (error, stdout, stderr) => {
            if (error) {
                console.error(`❌ Error starting ${service}:`, error);
                return res.status(500).json({ error: error.message });
            }
            res.json({ message: `Service ${service} completed`, output: stdout });
        });
    }
});

app.get('/api/status', (req, res) => {
    const scriptsDir = path.join(__dirname, '..', 'scripts');
    const overtimeStatusFile = path.join(scriptsDir, '.status_overtime.json');
    
    // Check Telegram Listener status
    exec('pgrep -f tg_listener.py', (error, stdout, stderr) => {
        const tgActive = !error && stdout.trim().length > 0;
        
        let overtimeStatus = { last_run: null, status: 'never' };
        if (fs.existsSync(overtimeStatusFile)) {
            try {
                overtimeStatus = JSON.parse(fs.readFileSync(overtimeStatusFile, 'utf8'));
            } catch (e) {
                console.error('Error parsing overtime status file:', e);
            }
        }
        
        let monitoringStatus = { active: false, status: 'stale', issues: 0 };
        const monFile = path.join(__dirname, 'public', 'data', 'monitoring.json');
        if (fs.existsSync(monFile)) {
            try {
                const stats = fs.statSync(monFile);
                const isFresh = (new Date() - stats.mtime) < (3 * 60 * 60 * 1000); // 3 hours
                
                const data = JSON.parse(fs.readFileSync(monFile, 'utf8'));
                let issues = 0;
                data.forEach(s => {
                    if (s.status === 'down' || s.expiryDate === 'Error') issues++;
                    if (s.expiryDate && s.expiryDate !== 'Unknown' && s.expiryDate !== 'Error') {
                        const daysObj = Math.floor((new Date(s.expiryDate) - new Date()) / (1000 * 60 * 60 * 24));
                        if (daysObj < 7) issues++;
                    }
                });
                
                monitoringStatus = {
                    active: isFresh,
                    status: isFresh ? (issues > 0 ? 'issues' : 'ok') : 'stale',
                    issues: issues
                };
            } catch (e) {
                console.error('Error reading monitoring.json:', e);
            }
        }
        
        res.json({
            telegram_listener: {
                active: tgActive,
                status: tgActive ? 'running' : 'stopped'
            },
            overtime_sync: overtimeStatus,
            monitoring: monitoringStatus
        });
    });
});

app.listen(port, () => {
    console.log(`🚀 Dashboard API server running at http://localhost:${port}`);
});

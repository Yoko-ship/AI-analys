import { execFileSync } from 'node:child_process';

export function pythonJson(source, args = [], options = {}) {
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  return JSON.parse(execFileSync(python, ['-X', 'utf8', '-c', source, ...args], {
    encoding: 'utf8', ...options,
  }));
}

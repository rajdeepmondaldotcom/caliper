import * as cp from 'child_process';
import * as vscode from 'vscode';

type StatusPayload = {
  today?: { credits?: number; api_dollars?: number };
  pricing?: { status?: string };
};

export function activate(context: vscode.ExtensionContext) {
  const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  item.command = 'caliper.openReceipt';
  context.subscriptions.push(item);

  const refresh = () => updateStatus(item);
  refresh();
  const interval = Math.max(5, vscode.workspace.getConfiguration('caliper').get('refreshSeconds', 30));
  const timer = setInterval(refresh, interval * 1000);
  context.subscriptions.push({ dispose: () => clearInterval(timer) });

  context.subscriptions.push(
    vscode.commands.registerCommand('caliper.openReceipt', () => openReceipt(context)),
  );
}

export function deactivate() {}

function updateStatus(item: vscode.StatusBarItem) {
  const command = vscode.workspace.getConfiguration('caliper').get('command', 'caliper');
  cp.execFile(command, ['statusline', '--format', 'json'], { timeout: 5000 }, (error: cp.ExecFileException | null, stdout: string) => {
    if (error !== null) {
      item.text = 'Caliper unavailable';
      item.tooltip = String(error.message || error);
      item.show();
      return;
    }
    const payload = JSON.parse(stdout || '{}') as StatusPayload;
    const credits = payload.today?.credits ?? 0;
    const dollars = payload.today?.api_dollars ?? 0;
    item.text = `Caliper ${credits.toFixed(0)} cr / $${dollars.toFixed(2)}`;
    item.tooltip = `Pricing: ${payload.pricing?.status ?? 'unknown'}`;
    item.show();
  });
}

function openReceipt(context: vscode.ExtensionContext) {
  const command = vscode.workspace.getConfiguration('caliper').get('command', 'caliper');
  cp.execFile(command, ['export', 'receipt', '--format', 'html'], { timeout: 10000 }, (error: cp.ExecFileException | null, stdout: string) => {
    if (error !== null) {
      void vscode.window.showErrorMessage(`Caliper receipt failed: ${error.message}`);
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      'caliperReceipt',
      'Caliper Receipt',
      vscode.ViewColumn.One,
      { enableScripts: false },
    );
    panel.webview.html = stdout;
    context.subscriptions.push(panel);
  });
}

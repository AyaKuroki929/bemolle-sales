#!/usr/bin/env python3
"""Claude通知BotのLINEに1通送る。GitHub Actions が失敗したときだけ呼ぶ。

  python3 notify_line.py "🚨 見出し"

本文には out.txt（直前の実行ログ）の先頭900文字と、実行画面のURLを添える。
LINE_TOKEN が無いときは何もせず終わる（勝手に送らない）。
"""
import json, os, sys, urllib.request

def main():
    token = os.environ.get('LINE_TOKEN', '')
    if not token:
        print('LINE_TOKEN が無いので送りません')
        return
    head = sys.argv[1] if len(sys.argv) > 1 else '🚨 エラーが起きました'
    body = ''
    if os.path.exists('out.txt'):
        body = open('out.txt', encoding='utf-8').read().strip()[:900]
    if not body:
        body = '中身が取れませんでした（実行そのものが落ちた可能性があります）'
    text = head + '\n\n' + body
    url = os.environ.get('RUN_URL', '')
    if url:
        text += '\n\n' + url
    req = urllib.request.Request(
        'https://api.line.me/v2/bot/message/broadcast',
        data=json.dumps({'messages': [{'type': 'text', 'text': text[:4900]}]}).encode(),
        method='POST',
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    print('LINEの応答:', urllib.request.urlopen(req).read().decode())


if __name__ == '__main__':
    main()

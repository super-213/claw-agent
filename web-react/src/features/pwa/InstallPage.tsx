import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import QRCode from 'qrcode';
import { ArrowLeft, Copy, Download, Share } from 'lucide-react';

export function InstallPage() {
  const [qr, setQr] = useState('');
  const [notice, setNotice] = useState('');
  const installed = window.matchMedia?.('(display-mode: standalone)').matches ||
    (window.navigator as Navigator & { standalone?: boolean }).standalone;
  const url = `${window.location.origin}/install`;
  const secure = window.isSecureContext;
  useEffect(() => {
    document.body.classList.add('pwa-install-route');
    let live = true;
    void QRCode.toDataURL(url, { width: 256, margin: 2, errorCorrectionLevel: 'M', color: { dark: '#163b3d', light: '#ffffff' } })
      .then(value => { if (live) setQr(value); }).catch(() => { if (live) setNotice('二维码暂时无法生成，请复制网址。'); });
    return () => { live = false; document.body.classList.remove('pwa-install-route'); };
  }, [url]);
  return <main className="pwa-install">
    <Link className="pwa-back" to="/home"><ArrowLeft size={18} /> 返回首页</Link>
    <img className="pwa-app-icon" src="/apple-touch-icon.png" width="80" height="80" alt="" />
    <p className="pwa-eyebrow">CLAW HOME AGENT</p>
    <h1>{installed ? '已在独立窗口中打开' : '把家庭助手放到主屏幕'}</h1>
    <p>点桌面图标直接打开，留更多空间给对话和生活资料。</p>
    {installed ? <Link className="pwa-primary" to="/home">进入家庭助手</Link> : <>
      {!secure && <p role="alert">请先通过 HTTPS 网址访问，以使用完整的安装与离线功能。</p>}
      <ol className="pwa-install-steps">
        <li><Share size={21} /><div><strong>在 Safari 打开本站</strong><span>如果在微信等应用里，请复制网址到 Safari。</span></div></li>
        <li><Download size={21} /><div><strong>打开分享菜单，选择“添加到主屏幕”</strong><span>部分版本先点页面菜单，再点“分享”。</span></div></li>
        <li><div className="pwa-step-number">3</div><div><strong>确认名称，然后点“添加”</strong><span>如果看到“作为 Web App 打开”，请保持开启。</span></div></li>
      </ol>
      <Link className="pwa-primary" to="/home">先在网页中使用</Link>
    </>}
    <section className="pwa-qr-section" aria-label="安装二维码">
      <div>{qr && <><img src={qr} width="192" height="192" alt="使用 iPhone 相机扫描，打开本站安装说明" /><a href={qr} download="home-agent-install.png">保存二维码</a></>}</div>
      <div><h2>用 iPhone 扫码打开</h2><p>二维码只包含本站安装页网址，添加时需要你手动确认。</p><p className="pwa-install-url">{url}</p>
        <button type="button" onClick={() => {
          if (!window.navigator.clipboard) { setNotice('请长按上方网址复制'); return; }
          void window.navigator.clipboard.writeText(url).then(() => setNotice('网址已复制')).catch(() => setNotice('请长按上方网址复制'));
        }}><Copy size={16} /> 复制网址</button>
      </div>
    </section>
    {notice && <p role="status">{notice}</p>}
    <p className="pwa-install-note">资料和对话仍由服务器提供，需要联网使用。添加到主屏幕后，首次打开可能需要重新登录。</p>
  </main>;
}

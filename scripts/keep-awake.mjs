// Streamlit Community Cloud 앱이 슬립에 빠지지 않게 실제 브라우저로 방문하는 스크립트.
// 단순 HTTP GET과 달리 진짜 세션(WebSocket)을 만들어 슬립 타이머를 리셋하고,
// 이미 잠들어 있으면 "Yes, get this app back up!" 버튼을 눌러 깨운다.
import { chromium } from 'playwright';

const APP_URL =
  process.env.APP_URL ||
  'https://barcode-app-khtraucisdge7xezgwdpxy.streamlit.app/';

const log = (...a) => console.log(new Date().toISOString(), ...a);

const browser = await chromium.launch();
const page = await browser.newPage();

try {
  log('방문 시작:', APP_URL);
  await page.goto(APP_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });

  // 슬립 페이지의 깨우기 버튼을 찾아서 누른다 (있을 때만).
  const wakeButton = page.getByRole('button', {
    name: /get this app back up|app back up|wake/i,
  });

  if (await wakeButton.count()) {
    log('앱이 잠들어 있음 → 깨우기 버튼 클릭');
    await wakeButton.first().click();
    // 깨어나는 데 시간이 걸리므로 앱 본문이 뜰 때까지 대기
    await page
      .waitForLoadState('networkidle', { timeout: 90000 })
      .catch(() => {});
  } else {
    log('앱이 이미 깨어있음 (깨우기 버튼 없음)');
  }

  // 실제 세션이 유지되도록 잠깐 머문다 (WebSocket 연결 확립용).
  await page.waitForTimeout(15000);

  const title = await page.title();
  log('완료. 페이지 제목:', title);
} catch (err) {
  log('오류:', err.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}

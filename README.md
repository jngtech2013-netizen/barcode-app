# 🚢 컨테이너 관리 시스템 (barcode_app)

Streamlit + Google Sheets 기반 컨테이너 등록 / 바코드(QR) 출력 / 통계 / 이력 관리 앱.

## 실행

```bash
pip install -r requirements.txt
streamlit run 1_등록.py
```

## 설정 (필수)

- **`.streamlit/secrets.toml`을 별도 경로에서 복사할 것** — Google Sheets 자격증명(`gcp_service_account`)이 들어 있으며 보안상 git에 포함되지 않으므로, 새 PC에서는 안전한 백업 경로에서 직접 복사해 넣어야 한다. (Streamlit Cloud 배포 시에는 앱 대시보드의 Settings → Secrets에 동일 내용을 입력)
- `config.json`(프린터 IP)은 없어도 실행되며, 설정 페이지에서 IP를 저장하면 자동 생성된다.

## 테스트

```bash
pip install -r requirements-dev.txt
python -m pytest
```

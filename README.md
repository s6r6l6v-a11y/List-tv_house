# List-tv_house 📺

Bot automático de validação e entrega da lista IPTV premium para o aplicativo **House Alves TV**.

## 🚀 Como funciona

1. A cada 6 horas (via GitHub Actions), o script `cloud_validator.py` é executado na nuvem.
2. O bot testa a latência real de cada canal (manifesto `.m3u8` e primeiro segmento `.ts`/`.aac`) com timeout de 1.8s.
3. Canais rápidos e estáveis são salvos automaticamente em:
   - `lista_premium.m3u`
   - `lista_premium.json`
4. O app **House Alves TV** na Smart TV LG lê diretamente os canais validados deste repositório sem consumir a RAM do computador.

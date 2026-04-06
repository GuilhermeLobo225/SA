# Configuração do Firebase

## 1. Criar Projeto

1. Ir a [Firebase Console](https://console.firebase.google.com/)
2. Criar novo projeto (ex: `smart-study-room`)
3. Desativar Google Analytics (opcional para protótipo)

## 2. Ativar Serviços

### Realtime Database
1. Build → Realtime Database → Create Database
2. Selecionar região (europe-west1)
3. Iniciar em **test mode** (para prototipagem)
4. Copiar o URL (ex: `https://smart-study-room-xxxxx.firebaseio.com`)

### Storage
1. Build → Storage → Get Started
2. Iniciar em **test mode**
3. Copiar o bucket (ex: `smart-study-room-xxxxx.appspot.com`)

### Authentication
1. Build → Authentication → Get Started
2. Ativar **Email/Password**
3. Criar duas contas de serviço:
   - `esp32cam@smartroom.local` (nó de visão)
   - `esp32env@smartroom.local` (nó ambiental)

## 3. Credenciais

### Para ESP32 (firmware `.ino`)
- API Key: Project Settings → General → Web API Key
- Database URL e Storage Bucket: copiados acima
- Email/Password das contas de serviço

### Para Python (processamento)
1. Project Settings → Service Accounts → Generate New Private Key
2. Guardar como `firebase_credentials.json` na pasta `processing/`
3. **Não incluir este ficheiro no Git!**

## 4. Regras de Segurança (Produção)

### Realtime Database
```json
{
  "rules": {
    "rooms": {
      ".read": true,
      ".write": "auth != null"
    }
  }
}
```

### Storage
```
rules_version = '2';
service firebase.storage {
  match /b/{bucket}/o {
    match /images/{allPaths=**} {
      allow read, write: if request.auth != null;
    }
  }
}
```

## 5. Estrutura da Base de Dados

```
rooms/
  sala_b1_piso2/
    latest_image: "images/sala_b1_piso2/20260401_143000.jpg"
    last_capture: "20260401_143000"
    occupancy/
      current/
        count: 8
        capacity: 20
        occupancy_pct: 40.0
        status: "disponivel"
        timestamp: "2026-04-01T14:30:05"
      history/
        -abc123/
          ...
    environment/
      current/
        temperature: 22.5
        humidity: 55.0
        air_quality: "aceitavel"
        light: "adequado"
        noise: "baixo"
        comfort: "bom"
        timestamp: "2026-04-01T14:30:00"
      history/
        -def456/
          ...
```

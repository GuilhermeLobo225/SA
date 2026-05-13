package pt.uminho.sa.data

/**
 * Constantes globais da aplicação.
 *
 * Mantemos tudo num único objeto para que, ao defender o projeto, seja fácil
 * apontar onde se altera o endpoint ou as coordenadas — não há valores
 * "mágicos" espalhados pelo código.
 */
object Config {

    /**
     * URL base da API REST que corre no PC (processing/api.py).
     *
     *  - No emulador Android, "localhost" do PC vê-se em 10.0.2.2
     *  - Num dispositivo físico, trocar para o IP do PC na LAN (ex: 192.168.1.50)
     *
     * O network_security_config.xml já autoriza estes hosts em cleartext (HTTP).
     */
    const val API_BASE = "http://10.0.2.2:5000/api"

    /** Período de polling à API (ms). Alinhado com a frequência dos nós ESP32 (30 s) */
    const val REFRESH_INTERVAL_MS = 15_000L

    /** Timeout dos pedidos HTTP (ms). Mantemos curto para falhar rápido para o mock. */
    const val HTTP_TIMEOUT_MS = 3_000

    /** Coordenadas aproximadas da BG no campus de Gualtar (PL8 — geofencing). */
    const val BG_LAT = 41.5611
    const val BG_LON = -8.3973

    /**
     * Raio da geofence em metros. Os PLs avisam que abaixo de 100–150 m
     * o sinal GPS pode oscilar e dar falsos positivos.
     */
    const val BG_RADIUS_M = 150f

    /** ID interno da geofence (necessário para a registar/remover). */
    const val BG_GEOFENCE_ID = "BG_GUALTAR"

    /** Canal de notificações usado nos alertas de geofence. */
    const val NOTIF_CHANNEL_GEOFENCE = "geofence_alerts"
}

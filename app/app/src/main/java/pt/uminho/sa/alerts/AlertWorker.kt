package pt.uminho.sa.alerts

import android.Manifest
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import pt.uminho.sa.R
import pt.uminho.sa.data.ApiClient
import pt.uminho.sa.data.AssetLoader
import pt.uminho.sa.data.Config
import pt.uminho.sa.data.RoomData
import pt.uminho.sa.ui.BibliotecaDetalheActivity
import kotlin.math.roundToInt

/**
 * Worker periódico: vai à API buscar o estado da sala monitorizada (BG) e
 * dispara notificações para as regras que o utilizador tem ativas.
 *
 * Roda no minimal interval do WorkManager (15 minutos). Cada regra usa um
 * NotificationCompat com `tag` próprio para que reaparecer não acumule
 * notificações — a nova substitui a anterior do mesmo tipo.
 *
 * Como é um CoroutineWorker, o `doWork()` corre num scope IO e pode chamar
 * `ApiClient.fetchRoom` (já suspend) sem complicar.
 */
class AlertWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val ctx = applicationContext
        val cfg = AlertPreferences.load(ctx)
        if (!cfg.enabled || !cfg.anyRuleActive) {
            // Utilizador desligou tudo entre dois ticks — não fazemos nada.
            return Result.success()
        }
        if (!notificationsAllowed(ctx)) {
            // Sem permissão de notificações em Android 13+ não dispara mesmo.
            return Result.success()
        }

        val biblio = AssetLoader.findBiblioteca(ctx, "bg") ?: return Result.success()
        val dados = ApiClient.fetchRoom(biblio.apiRoomId ?: biblio.id)

        if (cfg.occupancyEnabled)   avaliarOcupacao(ctx, biblio.id, dados, cfg.occupancyThresholdPct)
        if (cfg.temperatureEnabled) avaliarTemperatura(ctx, biblio.id, dados)
        if (cfg.noiseEnabled)       avaliarRuido(ctx, biblio.id, dados)

        return Result.success()
    }

    /* ============================================================
       Regras
       ============================================================ */

    private fun avaliarOcupacao(ctx: Context, bibliotecaId: String, d: RoomData, limiarPct: Int) {
        if (d.capacity <= 0) return
        val pct = (d.occupancyPct * 100).roundToInt()
        if (pct > limiarPct) return    // só notifica quando há espaço (abaixo do limiar)
        val titulo = ctx.getString(R.string.alert_occ_title)
        val texto  = ctx.getString(R.string.alert_occ_msg, pct, limiarPct, d.chairsFree.coerceAtLeast(d.capacity - d.count))
        notificar(ctx, bibliotecaId, "occ", titulo, texto, NOTIF_ID_OCC)
    }

    private fun avaliarTemperatura(ctx: Context, bibliotecaId: String, d: RoomData) {
        val t = d.temperature ?: return
        if (t in 20.0..26.0) return
        val titulo = ctx.getString(R.string.alert_temp_title)
        val texto  = ctx.getString(R.string.alert_temp_msg, t)
        notificar(ctx, bibliotecaId, "temp", titulo, texto, NOTIF_ID_TEMP)
    }

    private fun avaliarRuido(ctx: Context, bibliotecaId: String, d: RoomData) {
        val ruidoElevado = d.noise == "elevado" || d.noise == "muito_elevado" ||
                           (d.noiseDb?.let { it >= 55.0 } ?: false)
        if (!ruidoElevado) return
        val medida = d.noiseDb?.let { "${"%.1f".format(it)} dB" } ?: (d.noise ?: "elevado")
        val titulo = ctx.getString(R.string.alert_noise_title)
        val texto  = ctx.getString(R.string.alert_noise_msg, medida)
        notificar(ctx, bibliotecaId, "noise", titulo, texto, NOTIF_ID_NOISE)
    }

    /* ============================================================
       Notificações
       ============================================================ */

    private fun notificar(
        ctx: Context,
        bibliotecaId: String,
        tag: String,
        titulo: String,
        texto: String,
        id: Int
    ) {
        val abrirIntent = Intent(ctx, BibliotecaDetalheActivity::class.java).apply {
            putExtra("biblioteca_id", bibliotecaId)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pi = PendingIntent.getActivity(
            ctx, id, abrirIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notif = NotificationCompat.Builder(ctx, Config.NOTIF_CHANNEL_ALERTS)
            .setSmallIcon(R.drawable.ic_book)
            .setColor(ContextCompat.getColor(ctx, R.color.uminho_red))
            .setContentTitle(titulo)
            .setContentText(texto)
            .setStyle(NotificationCompat.BigTextStyle().bigText(texto))
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .setContentIntent(pi)
            .build()
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(tag, id, notif)
    }

    private fun notificationsAllowed(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true
        return ContextCompat.checkSelfPermission(
            ctx, Manifest.permission.POST_NOTIFICATIONS
        ) == PackageManager.PERMISSION_GRANTED
    }

    companion object {
        private const val NOTIF_ID_OCC   = 2001
        private const val NOTIF_ID_TEMP  = 2002
        private const val NOTIF_ID_NOISE = 2003
    }
}

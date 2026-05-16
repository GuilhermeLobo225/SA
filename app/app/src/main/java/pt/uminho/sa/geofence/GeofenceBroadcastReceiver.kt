package pt.uminho.sa.geofence

import android.Manifest
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.google.android.gms.location.Geofence
import com.google.android.gms.location.GeofenceStatusCodes
import com.google.android.gms.location.GeofencingEvent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import pt.uminho.sa.R
import pt.uminho.sa.data.ApiClient
import pt.uminho.sa.data.AssetLoader
import pt.uminho.sa.data.Config
import pt.uminho.sa.ui.BibliotecaDetalheActivity

/**
 * Apanha as transições de geofence registadas pelo GeofenceHandler.
 *
 * Fluxo:
 *   1. Sistema deteta que o telemóvel entrou na zona da BG
 *   2. Despoleta um Intent → este receiver
 *   3. Aqui consultamos a API para a ocupação atual e disparamos uma
 *      notificação para o utilizador.
 *
 * Esta junção entre geofencing e API REST é o que torna a feature útil:
 * o utilizador só recebe um alerta quando está perto da BG, e o alerta já
 * traz informação relevante para decidir se vale a pena entrar.
 *
 * Nota técnica: como precisamos de fazer um pedido HTTP a partir do receiver,
 * usamos `goAsync()` para evitar que o sistema mate o receiver antes da
 * resposta chegar. Temos cerca de 30 s neste modo.
 */
class GeofenceBroadcastReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val event = GeofencingEvent.fromIntent(intent) ?: return

        if (event.hasError()) {
            val msg = GeofenceStatusCodes.getStatusCodeString(event.errorCode)
            Log.e(TAG, "Erro na transição de geofence: $msg")
            return
        }

        // Pode haver várias geofences disparadas no mesmo evento — tratamos cada uma
        val geofencesAtivadas = event.triggeringGeofences ?: return
        val transition = event.geofenceTransition

        // Mantém o receiver vivo enquanto a corrotina trata todas as transições.
        val pendingResult = goAsync()
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            try {
                for (g in geofencesAtivadas) {
                    when (transition) {
                        Geofence.GEOFENCE_TRANSITION_ENTER -> tratarEntrada(context, g.requestId)
                        Geofence.GEOFENCE_TRANSITION_EXIT  -> tratarSaida(context, g.requestId)
                        else -> { /* DWELL ou outros — não usamos */ }
                    }
                }
            } finally {
                pendingResult.finish()
            }
        }
    }

    /* ---------- ENTER: vai à API buscar a ocupação e notifica ---------- */

    private suspend fun tratarEntrada(context: Context, geofenceId: String) {
        if (geofenceId != Config.BG_GEOFENCE_ID) return
        val biblio = AssetLoader.findBiblioteca(context, "bg") ?: return

        val dados = ApiClient.fetchRoom(biblio.apiRoomId ?: biblio.id)
        val pct = (dados.occupancyPct * 100).toInt()

        val titulo = context.getString(R.string.geofence_enter_title, biblio.nome)
        val texto  = context.getString(
            R.string.geofence_enter_msg,
            dados.count, dados.capacity, pct
        )
        mostrarNotificacao(context, biblio.id, titulo, texto, NOTIF_ID_ENTER)
    }

    /* ---------- EXIT: notificação simples de despedida ---------- */

    private fun tratarSaida(context: Context, geofenceId: String) {
        if (geofenceId != Config.BG_GEOFENCE_ID) return
        val biblio = AssetLoader.findBiblioteca(context, "bg") ?: return

        val titulo = context.getString(R.string.geofence_exit_title, biblio.nome)
        val texto  = context.getString(R.string.geofence_exit_msg)
        mostrarNotificacao(context, biblio.id, titulo, texto, NOTIF_ID_EXIT)
    }

    /* ---------- Construção e envio da notificação ---------- */

    private fun mostrarNotificacao(
        context: Context,
        bibliotecaId: String,
        titulo: String,
        texto: String,
        notifId: Int
    ) {
        // Verificação de permissão para Android 13+
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(
                context, Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
            if (!granted) {
                Log.w(TAG, "POST_NOTIFICATIONS não concedida — notificação suprimida")
                return
            }
        }

        // Tap na notificação → abre o detalhe da biblioteca
        val abrirIntent = Intent(context, BibliotecaDetalheActivity::class.java).apply {
            putExtra("biblioteca_id", bibliotecaId)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pi = PendingIntent.getActivity(
            context, notifId, abrirIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notif = NotificationCompat.Builder(context, Config.NOTIF_CHANNEL_GEOFENCE)
            .setSmallIcon(R.drawable.ic_book)
            .setColor(ContextCompat.getColor(context, R.color.uminho_red))
            .setContentTitle(titulo)
            .setContentText(texto)
            .setStyle(NotificationCompat.BigTextStyle().bigText(texto))
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .setContentIntent(pi)
            .build()

        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(notifId, notif)
    }

    companion object {
        private const val TAG = "GeofenceReceiver"
        private const val NOTIF_ID_ENTER = 1001
        private const val NOTIF_ID_EXIT  = 1002
    }
}

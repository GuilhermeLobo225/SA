package pt.uminho.sa.geofence

import android.Manifest
import android.annotation.SuppressLint
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.annotation.RequiresPermission
import com.google.android.gms.location.Geofence
import com.google.android.gms.location.GeofencingClient
import com.google.android.gms.location.GeofencingRequest
import com.google.android.gms.location.LocationServices
import pt.uminho.sa.data.Config

/**
 * Wrapper sobre a Geofencing API da Google.
 *
 * Responsabilidades:
 *   1. Construir a Geofence em si (createGeofence)
 *   2. Construir o GeofencingRequest (getGeofencingRequest)
 *   3. Registar/remover a geofence no GeofencingClient
 */
class GeofenceHandler(private val context: Context) {

    private val geofencingClient: GeofencingClient =
        LocationServices.getGeofencingClient(context)

    /**
     * PendingIntent que aponta para o nosso BroadcastReceiver. É reutilizado
     * entre addGeofences() e removeGeofences() — daí FLAG_UPDATE_CURRENT.
     * FLAG_MUTABLE é obrigatório a partir de Android 12.
     */
    private val pendingIntent: PendingIntent by lazy {
        val intent = Intent(context, GeofenceBroadcastReceiver::class.java)
        PendingIntent.getBroadcast(
            context,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
        )
    }

    /* ============================================================
       Construtores da Geofence
       ============================================================ */

    fun createGeofence(id: String, lat: Double, lng: Double, radius: Float): Geofence {
        return Geofence.Builder()
            .setRequestId(id)
            .setCircularRegion(lat, lng, radius)
            .setExpirationDuration(Geofence.NEVER_EXPIRE)
            .setTransitionTypes(
                Geofence.GEOFENCE_TRANSITION_ENTER or
                Geofence.GEOFENCE_TRANSITION_EXIT
            )
            .build()
    }

    fun getGeofencingRequest(geofence: Geofence): GeofencingRequest {
        return GeofencingRequest.Builder().apply {
            setInitialTrigger(GeofencingRequest.INITIAL_TRIGGER_ENTER)
            addGeofence(geofence)
        }.build()
    }

    /* ============================================================
       Operações de alto nível usadas pela Activity
       ============================================================ */

    /**
     * Regista a geofence da Biblioteca Geral. Recebe callbacks para a UI
     * poder mostrar Toasts ou snackbars de sucesso/erro.
     *
     * É @SuppressLint porque o Android Studio não consegue verificar que a
     * Activity já pediu a permissão antes de chamar este método; quem chama é
     * que tem essa responsabilidade.
     */
    @SuppressLint("MissingPermission")
    @RequiresPermission(Manifest.permission.ACCESS_FINE_LOCATION)
    fun registarGeofenceBG(
        onSuccess: () -> Unit,
        onError:   (String) -> Unit
    ) {
        val geofence = createGeofence(
            id     = Config.BG_GEOFENCE_ID,
            lat    = Config.BG_LAT,
            lng    = Config.BG_LON,
            radius = Config.BG_RADIUS_M
        )
        val request = getGeofencingRequest(geofence)

        geofencingClient.addGeofences(request, pendingIntent).run {
            addOnSuccessListener {
                Log.d(TAG, "Geofence ${Config.BG_GEOFENCE_ID} registada")
                onSuccess()
            }
            addOnFailureListener { e ->
                Log.e(TAG, "Falhou registo de geofence: ${e.message}")
                onError(e.message ?: "erro desconhecido")
            }
        }
    }

    /** Remove a geofence da BG (usado pelo botão "Remover geofence"). */
    fun removerGeofenceBG(onDone: () -> Unit) {
        geofencingClient.removeGeofences(listOf(Config.BG_GEOFENCE_ID))
            .addOnCompleteListener { onDone() }
    }

    companion object { private const val TAG = "GeofenceHandler" }
}

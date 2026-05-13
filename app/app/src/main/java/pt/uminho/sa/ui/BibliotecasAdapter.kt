package pt.uminho.sa.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import pt.uminho.sa.R
import pt.uminho.sa.data.Biblioteca
import pt.uminho.sa.databinding.ItemBibliotecaBinding

/**
 * Adapter para a lista de bibliotecas do MainActivity.
 *
 * Usa ViewBinding (ativado em build.gradle.kts: buildFeatures { viewBinding = true })
 * para acedermos às views do XML por nome sem precisar de findViewById,
 * mantendo o estilo da PL5 mas mais conciso.
 */
class BibliotecasAdapter(
    private var bibliotecas: List<Biblioteca>,
    private val onClick: (Biblioteca) -> Unit
) : RecyclerView.Adapter<BibliotecasAdapter.VH>() {

    inner class VH(val b: ItemBibliotecaBinding) : RecyclerView.ViewHolder(b.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val inflater = LayoutInflater.from(parent.context)
        return VH(ItemBibliotecaBinding.inflate(inflater, parent, false))
    }

    override fun getItemCount(): Int = bibliotecas.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val biblio = bibliotecas[position]
        val ctx    = holder.itemView.context

        with(holder.b) {
            sigla.text     = "${biblio.sigla} · CAMPUS ${biblio.campus.uppercase()}"
            nome.text      = biblio.nome
            cidade.text    = biblio.cidade
            descricao.text = biblio.descricao
            lugares.text   = biblio.lugares.toString()
            // Mostra apenas o primeiro tramo do horário (até ao "|") para caber
            horario.text   = biblio.horarioLetivo.substringBefore("|").trim()

            // Faixa do topo: muda para o gradiente verde-vermelho se tem sensorização
            topBand.setBackgroundResource(
                if (biblio.sensorizacao) R.drawable.top_band_monitored
                else                     R.drawable.top_band_red
            )

            // Badge: estilo, cor e texto consoante o estado
            if (biblio.sensorizacao) {
                badge.text = ctx.getString(R.string.badge_monitorizada)
                badge.setBackgroundResource(R.drawable.badge_monitored)
                badge.setTextColor(ContextCompat.getColor(ctx, R.color.status_free))
            } else {
                badge.text = ctx.getString(R.string.badge_nao_monitorizada)
                badge.setBackgroundResource(R.drawable.badge_unmonitored)
                badge.setTextColor(ContextCompat.getColor(ctx, R.color.text_muted))
            }

            // Clique abre o detalhe (delegado ao MainActivity)
            cardRoot.setOnClickListener { onClick(biblio) }
        }
    }

    /** Permite ao MainActivity refrescar a lista (ex: pull-to-refresh). */
    fun submit(novas: List<Biblioteca>) {
        bibliotecas = novas
        notifyDataSetChanged()
    }
}

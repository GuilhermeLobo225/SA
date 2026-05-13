package pt.uminho.sa.ui

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import pt.uminho.sa.R
import pt.uminho.sa.data.Biblioteca
import pt.uminho.sa.data.Livro
import pt.uminho.sa.databinding.ItemLivroBinding

/**
 * Adapter da lista de livros (catálogo).
 *
 * Recebe também o mapa id→sigla das bibliotecas para conseguir mostrar a sigla
 * curta (ex: "BGUM") na coluna meta sem ter de andar a procurar a cada bind.
 */
class LivrosAdapter(
    private var livros: List<Livro>,
    private val siglasPorId: Map<String, String>
) : RecyclerView.Adapter<LivrosAdapter.VH>() {

    inner class VH(val b: ItemLivroBinding) : RecyclerView.ViewHolder(b.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val inflater = LayoutInflater.from(parent.context)
        return VH(ItemLivroBinding.inflate(inflater, parent, false))
    }

    override fun getItemCount(): Int = livros.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val livro = livros[position]
        val ctx   = holder.itemView.context

        with(holder.b) {
            titulo.text = livro.titulo
            autor.text  = livro.autor

            val sigla = siglasPorId[livro.bibliotecaId] ?: livro.bibliotecaId.uppercase()
            meta.text = "${livro.area} · ${livro.ano} · ${livro.cota} · $sigla"

            // Pill de disponibilidade: cor varia consoante exemplares disponíveis
            val disp = livro.exemplaresDisponiveis
            val tot  = livro.exemplaresTotal
            pill.text = "$disp de $tot"
            when {
                disp == 0  -> {
                    pill.setBackgroundResource(R.drawable.pill_out)
                    pill.setTextColor(ContextCompat.getColor(ctx, R.color.status_full))
                }
                disp <= 1  -> {
                    pill.setBackgroundResource(R.drawable.pill_few)
                    pill.setTextColor(ContextCompat.getColor(ctx, R.color.status_mid))
                }
                else       -> {
                    pill.setBackgroundResource(R.drawable.pill_ok)
                    pill.setTextColor(ContextCompat.getColor(ctx, R.color.status_free))
                }
            }
        }
    }

    fun submit(novos: List<Livro>) {
        livros = novos
        notifyDataSetChanged()
    }

    /** Helper para o CatalogoActivity construir o mapa id→sigla a partir das bibliotecas. */
    companion object {
        fun mapearSiglas(bibliotecas: List<Biblioteca>): Map<String, String> =
            bibliotecas.associate { it.id to it.sigla }
    }
}

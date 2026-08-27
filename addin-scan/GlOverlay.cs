// Spike de overlay OpenGL no viewport do SolidWorks.
//
// Assina o BufferSwapNotify da ModelView ativa e desenha um triângulo de
// teste no espaço do modelo (o contexto GL do SolidWorks está corrente
// durante o callback; coordenadas em METROS). Se isto renderizar estável na
// instalação do usuário — inclusive com o Enhanced Graphics Performance —
// o caminho está aberto para desenhar a malha do scan inteira com VBOs.
//
// Toggle: ligar assina o evento; desligar remove. Custo zero quando off.

using System;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

namespace SwScanAddin
{
    public class GlOverlay
    {
        // -------- OpenGL 1.1 (imediato — suficiente para o spike)
        private const uint GL_TRIANGLES = 0x0004;
        private const uint GL_LINE_LOOP = 0x0002;
        private const uint GL_LIGHTING = 0x0B50;
        private const uint GL_DEPTH_TEST = 0x0B71;

        [DllImport("opengl32.dll")] private static extern void glBegin(uint mode);
        [DllImport("opengl32.dll")] private static extern void glEnd();
        [DllImport("opengl32.dll")] private static extern void glVertex3d(double x, double y, double z);
        [DllImport("opengl32.dll")] private static extern void glColor4d(double r, double g, double b, double a);
        [DllImport("opengl32.dll")] private static extern void glDisable(uint cap);
        [DllImport("opengl32.dll")] private static extern void glEnable(uint cap);
        [DllImport("opengl32.dll")] private static extern bool glIsEnabled(uint cap);
        [DllImport("opengl32.dll")] private static extern void glLineWidth(float w);

        private ModelView? _view;
        private DModelViewEvents_BufferSwapNotifyEventHandler? _handler;

        public bool Active => _view != null;
        public int Frames { get; private set; }

        /// Liga o overlay na vista ativa. Retorna descrição do estado.
        public string Enable(ISldWorks app)
        {
            if (Active) return "overlay já ativo";
            var doc = (IModelDoc2?)app.ActiveDoc;
            if (doc == null) return "abra um documento (peça/montagem) primeiro";
            _view = (ModelView)doc.ActiveView;
            if (_view == null) return "sem vista ativa";
            Frames = 0;
            _handler = OnBufferSwap;
            _view.BufferSwapNotify += _handler;
            doc.GraphicsRedraw2();
            return "overlay LIGADO — um triângulo laranja deve aparecer na origem";
        }

        public string Disable()
        {
            if (_view != null && _handler != null)
            {
                try { _view.BufferSwapNotify -= _handler; } catch { }
            }
            var frames = Frames;
            _view = null;
            _handler = null;
            return $"overlay desligado ({frames} quadros desenhados)";
        }

        private int OnBufferSwap()
        {
            try
            {
                Frames++;
                bool luz = glIsEnabled(GL_LIGHTING);
                if (luz) glDisable(GL_LIGHTING);

                // triângulo 60x60 mm no plano XY da origem do modelo (metros)
                glColor4d(0.85, 0.47, 0.34, 0.85);
                glBegin(GL_TRIANGLES);
                glVertex3d(0.0, 0.0, 0.0);
                glVertex3d(0.06, 0.0, 0.0);
                glVertex3d(0.0, 0.06, 0.0);
                glEnd();

                // contorno por cima de tudo (sem depth) para achá-lo fácil
                glDisable(GL_DEPTH_TEST);
                glLineWidth(2.0f);
                glColor4d(0.18, 0.43, 0.71, 1.0);
                glBegin(GL_LINE_LOOP);
                glVertex3d(0.0, 0.0, 0.0);
                glVertex3d(0.06, 0.0, 0.0);
                glVertex3d(0.0, 0.06, 0.0);
                glEnd();
                glEnable(GL_DEPTH_TEST);

                if (luz) glEnable(GL_LIGHTING);
            }
            catch { }
            return 0;
        }
    }
}

"""Illustrate verified demo artifacts without recomputing simulation behavior."""
import argparse
import math
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))


def load_data(prefix, *, canonical=True):
    from scripts.demo import verify_data
    data = verify_data(prefix,canonical=canonical)
    if any(not math.isfinite(v) for v in data['theta']):
        raise ValueError('nonfinite demo trajectory')
    if any(not math.isfinite(r[k]) for r in data['controls'] for k in ('theta','cmd')):
        raise ValueError('nonfinite demo control value')
    return data


def frame_view(data, frame):
    if type(frame) is not int or not 0 <= frame < 150:
        raise ValueError('demo frame must be 0..149')
    stop = (frame+1)*20
    row = data['controls'][stop-1]
    return dict(stop=stop,tick=stop-1,state=row['state'],staleness=row['staleness'],
                up_lost=[k for k in data['up_lost'] if k<stop],
                down_lost=[k for k in data['down_lost'] if k<stop])


def render(prefix, output, *, canonical=True):
    data = load_data(prefix,canonical=canonical)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from PIL import Image

    output = Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    fig, axes = plt.subplots(3,1,figsize=(6.4,3.6),dpi=100,sharex=True,
                             gridspec_kw={'height_ratios':[2,2,1]})
    temporary = None
    try:
        fig.subplots_adjust(left=.115,right=.985,top=.83,bottom=.13,hspace=.30)
        fig.suptitle('Deterministic lockstep: demo-loss30',fontsize=10,y=.985)
        fig.text(.5,.91,'seed 20260902 | modeled loss 30% each direction from tick 200',ha='center',fontsize=7)
        readout = fig.text(.5,.85,'',ha='center',fontsize=7)
        x = [k*.002 for k in range(3000)]
        pitch, command, link = axes
        pitch.axhline(0,color='#bbbbbb',lw=.6)
        truth_line, = pitch.plot([],[],color='#176b99',lw=1.2,label='truth')
        observation, = pitch.plot([],[],color='#c17818',lw=.7,alpha=.7,label='held observation')
        bound = max(.01,max(abs(v) for v in data['theta']),max(abs(r['theta']) for r in data['controls']))*1.1
        pitch.set_ylim(-bound,bound);pitch.set_ylabel('pitch (rad)',fontsize=7)
        pitch.legend(loc='upper right',fontsize=6,ncol=2)
        command_line, = command.plot([],[],color='#176b99',lw=1)
        for stop in (-.12,.12):command.axhline(stop,color='#c17818',ls='--',lw=.7)
        command.set_ylim(-.135,.135);command.set_ylabel('requested\ngimbal (rad)',fontsize=7)
        up, = link.plot([],[],ls='none',marker='|',markersize=3,color='#b32e36',label='uplink loss')
        down, = link.plot([],[],ls='none',marker='|',markersize=3,color='#df8419',label='downlink loss')
        palette=ListedColormap(['#d4d9df','#9dbbd9','#a1c9a7','#566b85'])
        band=link.imshow([[0]],aspect='auto',extent=(0,.04,.62,.95),cmap=palette,
                         norm=BoundaryNorm([-.5,.5,1.5,2.5,3.5],4),interpolation='nearest')
        link.set_ylim(0,1);link.set_yticks([]);link.set_ylabel('link/state',fontsize=7)
        link.set_xlabel('simulation time (s)',fontsize=7)
        link.legend(loc='upper left',bbox_to_anchor=(0,1.18),fontsize=6,ncol=2,
                    borderaxespad=0,frameon=False)
        cursors=[ax.axvline(0,color='#536170',lw=.6,alpha=.7) for ax in axes]
        for ax in axes:
            ax.set_xlim(0,6);ax.tick_params(labelsize=7)
            ax.spines[['top','right']].set_visible(False)
        states = [r['state'] for r in data['controls']]
        labels = ['INIT','ARMED','FLYING','TERMINATED']
        def update(frame):
            view=frame_view(data,frame);n=view['stop']
            truth_line.set_data(x[:n],data['theta'][:n])
            observation.set_data(x[:n],[r['theta'] for r in data['controls'][:n]])
            command_line.set_data(x[:n],[r['cmd'] for r in data['controls'][:n]])
            up.set_data([k*.002 for k in view['up_lost']],[.43]*len(view['up_lost']))
            down.set_data([k*.002 for k in view['down_lost']],[.22]*len(view['down_lost']))
            band.set_data([states[:n]]);band.set_extent((0,n*.002,.62,.95))
            for cursor in cursors:cursor.set_xdata([view['tick']*.002]*2)
            state = labels[view['state']] + (' / stabilized' if view['state']==3 else '')
            readout.set_text(f"tick {view['tick']:04d} | stale {view['staleness']} ticks | {state}")
            return truth_line,observation,command_line,up,down,band,readout,*cursors
        animation=FuncAnimation(fig,update,frames=150,interval=40,blit=False,repeat=False)
        with tempfile.NamedTemporaryFile(dir=output.parent,suffix='.gif',delete=False) as file:
            temporary=Path(file.name)
        animation.save(temporary,writer=PillowWriter(fps=25),dpi=100)
        if temporary.stat().st_size>=1572864:
            raise ValueError('demo GIF exceeds size bound')
        with Image.open(temporary) as gif:
            if gif.size!=(640,360) or gif.n_frames!=150:
                raise ValueError('demo GIF dimensions/frame count mismatch')
            for n in range(gif.n_frames):
                gif.seek(n)
                if gif.info.get('duration')!=40:raise ValueError('demo GIF frame duration mismatch')
        os.replace(temporary,output)
        temporary=None
        print(f'wrote {output} (illustration; canonical data digest is the proof)')
    finally:
        plt.close(fig)
        if temporary is not None:temporary.unlink(missing_ok=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix',type=Path)
    parser.add_argument('--out',type=Path,default=ROOT/'docs/demo.gif')
    args=parser.parse_args(argv)
    try:
        render(args.prefix,args.out)
        return 0
    except (OSError,ValueError) as error:
        print('render_demo: '+str(error),file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())

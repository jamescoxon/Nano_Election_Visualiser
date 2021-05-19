import requests
import time
import random
import json 
import os

from flask import Flask
from flask import request, render_template, send_file
from flask import jsonify
from flask_socketio import SocketIO
from flask_apscheduler import APScheduler

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
async_mode = None

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode=async_mode)

scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

url = os.environ.get('RPC_URL', 'http://localhost:7076')
update_time = int(os.environ.get('UPDATE_TIME', '5'))
conf_active = {'action' : 'confirmation_active'}

elections_list = []
hash_dict = {}
broadcast_data = []

peer_ip = {}
rep_conf = {}
rep_cemented = {}

@scheduler.task('interval', id='do_job_1', seconds=update_time, misfire_grace_time=900)
def scheduled_task():
    print('SCHEDULE: Start')
    with scheduler.app.app_context():
        confirmation_quorum_command = {'action' : 'confirmation_quorum', 'peer_details': 'true'}
        x = requests.post(url, json = confirmation_quorum_command)
        confirmation_quorum_result = x.json()

        for peers in confirmation_quorum_result['peers']:
            ip_parts = str(peers['ip']).split(']')
            ip_address = ip_parts[0][1:]
#            print('{} : {}'.format(ip_address, peers['account']))
            peer_ip[ip_address] = peers['account']

        x = requests.post(url, json = conf_active)
        result = x.json()
        confs = result['confirmations']
        total_confs = int(result['unconfirmed'])

        while len(elections_list) < 20:
            random_conf = random.randrange(total_confs)
            elections_list.append(confs[random_conf])
            hash_dict[confs[random_conf]] = '0'

        broadcast_data.clear()
        for election in elections_list:
            if election not in confs:
                if election in hash_dict:
                    block_info = {'action' : 'block_info', 'json_block': 'true', 'hash': hash_dict[election] }
                    x = requests.post(url, json = block_info)
                    result = x.json()
                    print(result)
                    if 'confirmed' in result:
                        confirmed = result['confirmed']
                    else:
                        confirmed = 'false'
                    print(confirmed)
                    print()
                    if confirmed == 'false':
                        print('Dropping')
                        broadcast_data.append({ 'root' : election, 'hash' : hash_dict[election], 'tally' : '600000000' , 'rep_num' : '0' , 'status' : 'DROPPED'})
                    else:
                        print('Success')
                        broadcast_data.append({ 'root' : election, 'hash' : hash_dict[election], 'tally' : '600000000' , 'rep_num' : '0' , 'status' : 'SUCCESSFUL'})


                print('Removing election')
                elections_list.remove(election)

                if election in hash_dict:
                    del hash_dict[election]

            else:
                conf_command = {'action' : 'confirmation_info', 'json_block': 'true', 'root': election , 'representatives': 'true' }

                x = requests.post(url, json = conf_command)
                result = x.json()
#                print(result)
                total_tally = result['total_tally']
                last_winner = result['last_winner']
                representatives = result['blocks'][last_winner]['representatives']

                hash_dict[election] = last_winner
#                print('Winner: {}, Tally: {}'.format(last_winner, total_tally))
#            broadcast_data[last_winner] =  total_tally
                broadcast_data.append({ 'root' : election, 'hash' : last_winner, 'tally' : total_tally, 'rep_num' : len(representatives), 'status' : 'IN_PROGRESS'})

        broadcast_json = json.dumps(broadcast_data)
#        print(broadcast_json)
#        socketio.emit('update',{'data' : 'test'} , broadcast=True)
        print('SCHEDULE: Done')
        socketio.emit('update', broadcast_json , broadcast=True)

@socketio.on('connect')
def test_connect():
    print('connected')
    socketio.emit('my response', {'data': 'Connected'})

@app.route('/')
def start_page():
    return send_file('./templates/index.html')

@app.route('/conf/random')
def start():

    x = requests.post(url, json = conf_active)
    result = x.json()
    confs = result['confirmations']
    total_confs = int(result['unconfirmed'])
    print(total_confs)
    print('Last Conf: {}'.format(confs[-1]))
    random_conf = random.randrange(total_confs)
    return '<html><h1>Conf Monitor</h1><br>Here is a random election to monitor:<br><a href="https://nanostatus.live/conf/{}">{}</a></html>'.format(confs[random_conf], confs[random_conf])

@app.route('/conf/random/json')
def start_json():

    x = requests.post(url, json = conf_active)
    result = x.json()
    confs = result['confirmations']
    total_confs = int(result['unconfirmed'])
    print(total_confs)
    print('Last Conf: {}'.format(confs[-1]))
    random_conf = random.randrange(total_confs)
    return jsonify(confs[random_conf])

@app.route('/conf/<string:root>')
def conf_info(root):

    print('{} {}'.format(len(peer_ip), len(rep_conf)))
    rep_command = {'action' : 'telemetry', 'raw': 'true'}
    x = requests.post(url, json = rep_command)
    rep_result = x.json()

    for nodes in rep_result['metrics']:
        try:
#            if nodes['address'] in peer_ip:
#                print('Found address')
#            else:
#                print('Not present')

            node_address = peer_ip[nodes['address']]
            node_version = nodes['major_version']
            node_cemented_count = nodes['cemented_count']
            rep_conf[node_address] = node_version
            rep_cemented[node_address] = node_cemented_count
        except:
     #       print('Failed: {}'.format(nodes))
            pass

    conf_command = {'action' : 'confirmation_info', 'json_block': 'true', 'root': root ,'representatives': 'true'}

    x = requests.post(url, json = conf_command)
    result = x.json()

    if 'total_tally' in result:
        total_tally = result['total_tally']
    else:
        return '<html><head><meta http-equiv="refresh" content="5"></head>Election completed or dropped</html>'

    last_winner = result['last_winner']
    representatives = result['blocks'][last_winner]['representatives']

    representatives_list = '<table><tr><th>Rep</th><th>Weight</th><th>Name</th><th>Node Version</th><th>Cemented</th></tr>'

    balance = result['blocks'][last_winner]['contents']['balance']
    account = result['blocks'][last_winner]['contents']['account']

    for reps in representatives:
#        print(reps)
        if reps == 'nano_37imps4zk1dfahkqweqa91xpysacb7scqxf3jqhktepeofcxqnpx531b3mnt':
            name = 'Kraken'
        elif reps == 'nano_1b9wguhh39at8qtm93oghd6r4f4ubk7zmqc9oi5ape6yyz4s1gamuwn3jjit':
            name = '465i'
        elif reps == 'nano_1iuz18n4g4wfp9gf7p1s8qkygxw7wx9qfjq6a9aq68uyrdnningdcjontgar':
            name = 'NanoTicker'
        elif reps == 'nano_3jwrszth46rk1mu7rmb4rhm54us8yg1gw3ipodftqtikf5yqdyr7471nsg1k':
            name = 'Binance'
        elif reps == 'nano_3arg3asgtigae3xckabaaewkx3bzsh7nwz7jkmjos79ihyaxwphhm6qgjps4':
            name = 'NF 1'
        elif reps == 'nano_1natrium1o3z5519ifou7xii8crpxpk8y65qmkih8e8bpsjri651oza8imdd':
            name = 'Natrium'
        elif reps == 'nano_1awsn43we17c1oshdru4azeqjz9wii41dy8npubm4rg11so7dx3jtqgoeahy':
            name = 'NF 6'
        elif reps == 'nano_1stofnrxuz3cai7ze75o174bpm7scwj9jn3nxsn8ntzg784jf1gzn1jjdkou':
            name = 'NF 2'
        elif reps == 'nano_1anrzcuwe64rwxzcco8dkhpyxpi8kd7zsjc1oeimpc3ppca4mrjtwnqposrs':
            name = 'NF 7'
        elif reps == 'nano_1hza3f7wiiqa7ig3jczyxj5yo86yegcmqk3criaz838j91sxcckpfhbhhra1':
            name = 'NF 8'
        elif reps == 'nano_3dmtrrws3pocycmbqwawk6xs7446qxa36fcncush4s1pejk16ksbmakis78m':
            name = 'NF 4'
        elif reps == 'nano_3pczxuorp48td8645bs3m6c3xotxd3idskrenmi65rbrga5zmkemzhwkaznh':
            name = 'NanoWallet'
        elif reps == 'nano_3rw4un6ys57hrb39sy1qx8qy5wukst1iiponztrz9qiz6qqa55kxzx4491or':
            name = 'NanoVault'
        elif reps == 'nano_1center16ci77qw5w69ww8sy4i4bfmgfhr81ydzpurm91cauj11jn6y3uc5y':
            name = 'Nanocenter'
        elif reps == 'nano_1x7biz69cem95oo7gxkrw6kzhfywq4x5dupw4z1bdzkb74dk9kpxwzjbdhhs':
            name = 'Nanocrawler'
        elif reps == 'nano_3om9m65hb6c3xaqkhqpok48wq4dgxidnxt8fihknbsb8pf997iu6dx6x6mfu':
            name = 'Voxpopuli'
        elif reps == 'nano_1kd4h9nqaxengni43xy9775gcag8ptw8ddjifnm77qes1efuoqikoqy5sjq3':
            name = 'NanoQuake'
        elif reps == 'nano_16d45ow3tsj1y3z9n4satwzxgj6qiue1ggxbwbrj3b33qr58bzchkpsffpx4':
            name = '1NANO Community'
        elif reps == 'nano_1ninja7rh37ehfp9utkor5ixmxyg8kme8fnzc4zty145ibch8kf5jwpnzr3r':
            name = 'My Nano Ninja'
        elif reps == 'nano_3chartsi6ja8ay1qq9xg3xegqnbg1qx76nouw6jedyb8wx3r4wu94rxap7hg':
            name = 'Nano Charts'
        elif reps == 'nano_3pczxuorp48td8645bs3m6c3xotxd3idskrenmi65rbrga5zmkemzhwkaznh':
            name = 'NanoWallet.io'
        elif reps == 'nano_1natrium1o3z5519ifou7xii8crpxpk8y65qmkih8e8bpsjri651oza8imdd':
            name = 'Natrium'
        elif reps == 'nano_1wenanoqm7xbypou7x3nue1isaeddamjdnc3z99tekjbfezdbq8fmb659o7t':
            name = 'WeNano'
        elif reps == 'nano_3uaydiszyup5zwdt93dahp7mri1cwa5ncg9t4657yyn3o4i1pe8sfjbimbas':
            name = 'Nano.Voting'
        elif reps == 'nano_34zuxqdsucurhjrmpc4aixzbgaa4wjzz6bn5ryn56emc9tmd3pnxjoxfzyb6':
            name = 'Nano Germany'
        else:
            name = 'None'

        try:
            node_version = rep_conf[reps]
        except:
            node_version = 'failed'

        try:
            node_cemented = rep_cemented[reps]
        except:
            node_cemented = 'failed'

        representatives_list = '{}<tr><td>{}</td><td>{} Nano</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(representatives_list, reps, int(int(representatives[reps]) / 1000000000000000000000000000000), name, node_version, node_cemented)

    return '<html><head><meta http-equiv="refresh" content="5"></head>Last Winner: {}<br> Total Tally: {}<br>Account: {}<br>Block Balance: {}<br><br>{}</table></html>'.format(last_winner, total_tally, account, balance, representatives_list)


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0')

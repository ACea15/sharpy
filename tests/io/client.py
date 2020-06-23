import socket
import selectors
import time
import logging
import struct


logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=20)
logger = logging.getLogger(__name__)

sharpy_incoming = ('127.0.0.1', 65001)  # control side socket
sharpy_outgoing = ('127.0.0.1', 65000)  # output side socket

own_control = ('127.0.0.1', 64000)
own_receive = ('127.0.0.1', 64001)

in_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
in_sock.bind(own_control)

out_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
out_sock.bind(own_receive)

while True:

    # send control input to sharpy
    ctrl_value = struct.pack('f', 10)
    logger.info('Sending control input')
    in_sock.sendto(ctrl_value, sharpy_incoming)
    logger.info('Sent control input to {}'.format(sharpy_incoming))

    # time.sleep(2)
    input('Continue loop')

    # receive output data
    # req_message = b'I want data'  # this would be the RREF0 value
    # out_sock.sendto(req_message, sharpy_outgoing)
    # msg, conn = out_sock.recvfrom(413)
    # logger.info('Received {} data from {}'.format(msg, conn))

    input('Next time step')

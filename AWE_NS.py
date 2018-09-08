"""
@author: Maziar Raissi
"""

import sys
sys.path.insert(0, '../../Utilities/')

import tensorflow as tf
import numpy as np
import matplotlib.pyplot as plt
import scipy.io
from scipy.interpolate import griddata
from plotting import newfig, savefig
from mpl_toolkits.axes_grid1 import make_axes_locatable
import matplotlib.gridspec as gridspec
import time
import os
os.environ['CUDA_VISIBLE_DEVICES']='0'
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
np.random.seed(1234)
tf.set_random_seed(1234)

class PhysicsInformedNN:
    # Initialize the class
    def __init__(self, X, u, layers, layers_c, lb, ub):
        
        self.lb = lb
        self.ub = ub
        
        self.x = X[:,0:1]
        self.t = X[:,1:2]
        self.u = u
        
        self.layers = layers
        
        # Initialize NNs
        self.weights, self.biases = self.initialize_NN(layers)

        self.weights_c, self.biases_c = self.initialize_NN(layers_c)

        # tf placeholders and graph
        self.sess = tf.Session(config=tf.ConfigProto(allow_soft_placement=True,
                                                     log_device_placement=True))
        
        # Initialize parameters

        self.x_tf = tf.placeholder(tf.float32, shape=[None, self.x.shape[1]])
        self.t_tf = tf.placeholder(tf.float32, shape=[None, self.t.shape[1]])
        self.u_tf = tf.placeholder(tf.float32, shape=[None, self.u.shape[1]])

        self.c_tf = tf.placeholder(tf.float32, shape=[None, self.x.shape[1]])
                
        self.u_pred = self.net_u(self.x_tf, self.t_tf)
        self.f_pred = self.net_f(self.x_tf, self.t_tf)

        self.c_pred = self.net_c(self.x_tf)
        
        

        self.loss_u = tf.reduce_mean(tf.square(self.u_tf - self.u_pred))
        self.loss_f = tf.reduce_mean(tf.square(self.f_pred))*100

        self.loss = self.loss_u + self.loss_f

        self.u_norm = tf.reduce_mean(tf.square(self.u_tf))
        self.up_norm = tf.reduce_mean(tf.square(self.u_pred))

        self.u_t = tf.gradients(self.u_pred, self.t_tf)[0]
        self.u_tt = tf.gradients(self.u_t,self.t_tf)[0]
        self.u_x = tf.gradients(self.u_pred, self.x_tf)[0]
        self.u_xx = tf.gradients(self.u_x, self.x_tf)[0]

        
        
        self.optimizer = tf.contrib.opt.ScipyOptimizerInterface(self.loss, 
                                                                method = 'L-BFGS-B', 
                                                                options = {'maxiter': 50000,
                                                                           'maxfun': 50000,
                                                                           'maxcor': 50,
                                                                           'maxls': 50,
                                                                           'ftol' : 1.0 * np.finfo(float).eps})
    
        self.optimizer_Adam = tf.train.AdamOptimizer(learning_rate=0.001)
        #self.optimizer_Adam = tf.train.GradientDescentOptimizer(learning_rate=0.1)
        self.train_op_Adam = self.optimizer_Adam.minimize(self.loss)
        

        # tensor board
        tf.summary.scalar('loss',self.loss)
        tf.summary.histogram('weights',self.weights_c[3])
        tf.summary.scalar('u_norm',self.u_norm)
        tf.summary.scalar('up_norm',self.up_norm)
        tf.summary.scalar('loss_u',self.loss_u)
        tf.summary.scalar('loss_f',self.loss_f)
        #tf.summary.histogram('weights_c',self.weights_c[3])
        #tf.summary.scalar('u_pred',self.u_pred)
        #tf.summary.image('c_pred',self.c_pred)
        
        # tensor board
        tf.gfile.DeleteRecursively('./log')
        init = tf.global_variables_initializer()

        self.merged = tf.summary.merge_all()

        self.sess.run(init)

        self.writer = tf.summary.FileWriter('./log',self.sess.graph)

    def initialize_NN(self, layers):        
        weights = []
        biases = []
        num_layers = len(layers) 
        for l in range(0,num_layers-1):
            W = self.xavier_init(size=[layers[l], layers[l+1]])
            b = tf.Variable(tf.zeros([1,layers[l+1]], dtype=tf.float32), dtype=tf.float32)
            weights.append(W)
            biases.append(b)        
        return weights, biases
        
    def xavier_init(self, size):
        in_dim = size[0]
        out_dim = size[1]        
        xavier_stddev = np.sqrt(2/(in_dim + out_dim))
        return tf.Variable(tf.truncated_normal([in_dim, out_dim], stddev=xavier_stddev), dtype=tf.float32)
    
    def neural_net(self, X, weights, biases):
        num_layers = len(weights) + 1
        
        H = 2.0*(X - self.lb)/(self.ub - self.lb) - 1.0
        for l in range(0,num_layers-2):
            W = weights[l]
            b = biases[l]
            H = tf.tanh(tf.add(tf.matmul(H, W), b))
        W = weights[-1]
        b = biases[-1]
        Y = tf.add(tf.matmul(H, W), b)
        return Y

    # a network which only use x, without t
    def neural_net_x(self, X, weights, biases):
        num_layers = len(weights) + 1
        H = 2.0*(X - self.lb[0])/(self.ub[0] - self.lb[0]) - 1.0
        for l in range(0,num_layers-2):
            W = weights[l]
            b = biases[l]
            H = tf.nn.relu(tf.add(tf.matmul(H, W), b))
        W = weights[-1]
        b = biases[-1]
        Y = tf.add(tf.matmul(H, W), b)
        return Y        
    
    # define lambda_1 and lambda_2
    def net_c(self,x):
        c = self.neural_net_x(x, self.weights_c, self.biases_c)
        return c

    def net_u(self, x, t):  
        u = self.neural_net(tf.concat([x,t],1), self.weights, self.biases)
        return u
    
    def net_f(self, x, t):
        c = self.net_c(x)
        u = self.net_u(x,t)
        u_t = tf.gradients(u, t)[0]
        u_tt = tf.gradients(u_t,t)[0]
        u_x = tf.gradients(u, x)[0]
        u_xx = tf.gradients(u_x, x)[0]

        f =  c * u_xx - u_tt 
        
        return f
    
    def callback(self, loss):
        print('Loss: %e' % (loss))
        
        
    def train(self, nIter):
        tf_dict = {self.x_tf: self.x, self.t_tf: self.t, self.u_tf: self.u}
        
        start_time = time.time()



        for it in range(nIter):
            _, summary = self.sess.run([self.train_op_Adam,self.merged], tf_dict)
            self.writer.add_summary(summary,it)
            # Print
            if it % 10 == 0:
                elapsed = time.time() - start_time
                loss_value = self.sess.run(self.loss, tf_dict)
                print('It: %d, Loss: %.3e, Time: %.2f' % (it, loss_value, elapsed))
        
        self.writer.close()

        # self.optimizer.minimize(self.sess,
        #                         feed_dict = tf_dict,
        #                         fetches = [self.loss],
        #                         loss_callback = self.callback)
        
        
    def predict(self, X_star):
        
        tf_dict = {self.x_tf: X_star[:,0:1], self.t_tf: X_star[:,1:2]}
        
        u_star = self.sess.run(self.u_pred, tf_dict)
        f_star = self.sess.run(self.f_pred, tf_dict)
        c_star = self.sess.run(self.c_pred, tf_dict)

        [ut_star, utt_star, ux_star, uxx_star] = self.sess.run([self.u_t,self.u_tt,self.u_x,self.u_xx], tf_dict)

        
        return u_star, f_star, c_star, ut_star, utt_star, ux_star, uxx_star

    
if __name__ == "__main__": 
    

    N_u = 1000
    layers = [2, 20, 20, 20, 20, 20, 20, 20, 20, 1]
    layers_c = [1, 10, 10, 10, 10, 1]
    
    data = scipy.io.loadmat('../Data/FD_1D_DX4_DT2_YU.mat')
    #data = scipy.io.loadmat('../Data/burgers_shock.mat')
    
    t = data['t'].flatten()[:,None]
    x = data['x'].flatten()[:,None]
    #Exact = np.real(data['usol']).T
    Exact = np.real(data['seis_u'])
    
    X, T = np.meshgrid(x,t)
    
    X_star = np.hstack((X.flatten()[:,None], T.flatten()[:,None]))
    u_star = Exact.flatten()[:,None]              

    # Doman bounds
    lb = X_star.min(0)
    ub = X_star.max(0)  
    
    ######################################################################
    ######################## Noiseles Data ###############################
    ######################################################################
    noise = 0.0            
             
    idx = np.random.choice(X_star.shape[0], N_u, replace=False)
    X_u_train = X_star[idx,:]
    u_train = u_star[idx,:]
    
    model = PhysicsInformedNN(X_u_train, u_train, layers, layers_c, lb, ub)
    model.train(2000)
    
    u_pred, f_pred, c_pred, ut_star, utt_star, ux_star, uxx_star = model.predict(X_star)
    
    print(c_pred)

    error_u = np.linalg.norm(u_star-u_pred,2)/np.linalg.norm(u_star,2)
    
    U_pred = griddata(X_star, u_pred.flatten(), (X, T), method='cubic')




    scipy.io.savemat('result.mat', {'u_pred':u_pred,'c_pred':c_pred,'U_pred':U_pred,
        'X_u_train':X_u_train,'u_train':u_train,'Exact':Exact,'f_pred':f_pred,
        'ut_star':ut_star,'utt_star':utt_star,'ux_star':ux_star,'uxx_star':uxx_star})
        
    # lambda_1_value = model.sess.run(model.lambda_1)
    # lambda_2_value = model.sess.run(model.lambda_2)
    # lambda_2_value = np.exp(lambda_2_value)
    
    # error_lambda_1 = np.abs(lambda_1_value - 1.0)*100
    # error_lambda_2 = np.abs(lambda_2_value - nu)/nu * 100
    
    # print('Error u: %e' % (error_u))    
    # print('Error l1: %.5f%%' % (error_lambda_1))                             
    # print('Error l2: %.5f%%' % (error_lambda_2))  
    
    ######################################################################
    ########################### Noisy Data ###############################
    ######################################################################
    # noise = 0.01        
    # u_train = u_train + noise*np.std(u_train)*np.random.randn(u_train.shape[0], u_train.shape[1])
        
    # model = PhysicsInformedNN(X_u_train, u_train, layers, lb, ub)
    # model.train(10000)
    
    # u_pred, f_pred = model.predict(X_star)
        
    # lambda_1_value_noisy = model.sess.run(model.lambda_1)
    # lambda_2_value_noisy = model.sess.run(model.lambda_2)
    # lambda_2_value_noisy = np.exp(lambda_2_value_noisy)
            
    # error_lambda_1_noisy = np.abs(lambda_1_value_noisy - 1.0)*100
    # error_lambda_2_noisy = np.abs(lambda_2_value_noisy - nu)/nu * 100
    
    # print('Error lambda_1: %f%%' % (error_lambda_1_noisy))
    # print('Error lambda_2: %f%%' % (error_lambda_2_noisy))                           

 
    ######################################################################
    ############################# Plotting ###############################
    ######################################################################    
    
    # fig, ax = newfig(1.0, 1.4)
    # ax.axis('off')
    
    # ####### Row 0: u(t,x) ##################    
    # gs0 = gridspec.GridSpec(1, 2)
    # gs0.update(top=1-0.06, bottom=1-1.0/3.0+0.06, left=0.15, right=0.85, wspace=0)
    # ax = plt.subplot(gs0[:, :])
    
    # h = ax.imshow(U_pred.T, interpolation='nearest', cmap='rainbow', 
    #               extent=[t.min(), t.max(), x.min(), x.max()], 
    #               origin='lower', aspect='auto')
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes("right", size="5%", pad=0.05)
    # fig.colorbar(h, cax=cax)
    
    # ax.plot(X_u_train[:,1], X_u_train[:,0], 'kx', label = 'Data (%d points)' % (u_train.shape[0]), markersize = 2, clip_on = False)
    
    # line = np.linspace(x.min(), x.max(), 2)[:,None]
    # ax.plot(t[25]*np.ones((2,1)), line, 'w-', linewidth = 1)
    # ax.plot(t[50]*np.ones((2,1)), line, 'w-', linewidth = 1)
    # ax.plot(t[75]*np.ones((2,1)), line, 'w-', linewidth = 1)
    
    # ax.set_xlabel('$t$')
    # ax.set_ylabel('$x$')
    # ax.legend(loc='upper center', bbox_to_anchor=(1.0, -0.125), ncol=5, frameon=False)
    # ax.set_title('$u(t,x)$', fontsize = 10)
    
    # ####### Row 1: u(t,x) slices ##################    
    # gs1 = gridspec.GridSpec(1, 3)
    # gs1.update(top=1-1.0/3.0-0.1, bottom=1.0-2.0/3.0, left=0.1, right=0.9, wspace=0.5)
    
    # ax = plt.subplot(gs1[0, 0])
    # ax.plot(x,Exact[25,:], 'b-', linewidth = 2, label = 'Exact')       
    # ax.plot(x,U_pred[25,:], 'r--', linewidth = 2, label = 'Prediction')
    # ax.set_xlabel('$x$')
    # ax.set_ylabel('$u(t,x)$')    
    # ax.set_title('$t = 0.25$', fontsize = 10)
    # ax.axis('square')
    # ax.set_xlim([-1.1,1.1])
    # ax.set_ylim([-1.1,1.1])
    
    # ax = plt.subplot(gs1[0, 1])
    # ax.plot(x,Exact[50,:], 'b-', linewidth = 2, label = 'Exact')       
    # ax.plot(x,U_pred[50,:], 'r--', linewidth = 2, label = 'Prediction')
    # ax.set_xlabel('$x$')
    # ax.set_ylabel('$u(t,x)$')
    # ax.axis('square')
    # ax.set_xlim([-1.1,1.1])
    # ax.set_ylim([-1.1,1.1])
    # ax.set_title('$t = 0.50$', fontsize = 10)
    # ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.35), ncol=5, frameon=False)
    
    # ax = plt.subplot(gs1[0, 2])
    # ax.plot(x,Exact[75,:], 'b-', linewidth = 2, label = 'Exact')       
    # ax.plot(x,U_pred[75,:], 'r--', linewidth = 2, label = 'Prediction')
    # ax.set_xlabel('$x$')
    # ax.set_ylabel('$u(t,x)$')
    # ax.axis('square')
    # ax.set_xlim([-1.1,1.1])
    # ax.set_ylim([-1.1,1.1])    
    # ax.set_title('$t = 0.75$', fontsize = 10)
    
    # ####### Row 3: Identified PDE ##################    
    # gs2 = gridspec.GridSpec(1, 3)
    # gs2.update(top=1.0-2.0/3.0, bottom=0, left=0.0, right=1.0, wspace=0.0)
    
    # ax = plt.subplot(gs2[:, :])
    # ax.axis('off')
    # s1 = r'$\begin{tabular}{ |c|c| }  \hline Correct PDE & $u_t + u u_x - 0.0031831 u_{xx} = 0$ \\  \hline Identified PDE (clean data) & '
    # s2 = r'$u_t + %.5f u u_x - %.7f u_{xx} = 0$ \\  \hline ' % (lambda_1_value, lambda_2_value)
    # s3 = r'Identified PDE (1\% noise) & '
    # s4 = r'$u_t + %.5f u u_x - %.7f u_{xx} = 0$  \\  \hline ' % (lambda_1_value_noisy, lambda_2_value_noisy)
    # s5 = r'\end{tabular}$'
    # s = s1+s2+s3+s4+s5
    # ax.text(0.1,0.1,s)
        
    # savefig('./figures/Burgers_identification')  
    




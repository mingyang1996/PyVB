#!/usr/bin/python

import numpy as np
from numpy.random import random, dirichlet
from scipy.cluster import vq
from scipy.special import digamma
from hmm import _BaseHMM, test_model
from util import log_like_Gauss2
from moments import *

class _BaseVBHMM(_BaseHMM):
    """
    This is a base class for HMM with Variational Bayesian Learning
    All VB-HMM should be an inheritant of this class
    """
    def __init__(self,N,uPi0=0.5,uA0=0.5):
        _BaseHMM.__init__(self,N)
    
        # hyperparameters for prior
        # for initial prob
        self._uPi = np.ones(N) * uPi0
        # for transition prob
        self._uA = np.ones((N,N)) * uA0
        
        # parameters for posterior
        # for initial prob
        self._WPi = np.array(self._uPi)
        # for transition prob
        self._WA = np.array(self._uA)
    
    def score(self,obs):
        """
        score the model
        input
          obs [ndarray, shape(nobs,ndim)] : observed data
        output
          F [float] : variational free energy of the model
        """
        z,lnP = self.eval_hidden_states(obs)
        F = -lnP + self._KL_div()
        return F
    
    def fit(self,obs,niter=10000,eps=1.0e-4,ifreq=10,\
        init=True,use_ext="F"):
        """
        Fit the HMM via VB-EM algorithm
        """
        if init:
            self._initialize_HMM(obs)
            old_F = 1.0e20
            lnalpha, lnbeta, lneta = self._allocate_temp(obs)
            
        for i in xrange(niter):
            # VB-E step
            lnf = self._log_like_f(obs)
            lneta,lngamma, lnP = self._E_step(lnf,lnalpha,lnbeta,lneta,use_ext)

            # check convergence
            KL = self._KL_div()
            F = -lnP + KL
            dF = F - old_F
            if(abs(dF) < eps):
                print "%8dth iter, Free Energy = %12.6e, dF = %12.6e" %(i,F,dF)
                print "%12.6e < %12.6e Converged" %(dF, eps)
                break
            if i % ifreq == 0 and dF < 0.0:
                print "%6dth iter, F = %15.8e  df = %15.8e"%(i,F,dF)
            elif dF >= 0.0:
                print "%6dth iter, F = %15.8e  df = %15.8e warning"%(i,F,dF)
        
            old_F = F

            # update parameters via VB-M step
            self._M_step(obs,lneta,lngamma,use_ext)

        return self

    def fit_multi(self,obss,niter=1000,eps=1.0e-4,ifreq=10,\
            init=True,use_ext="F"):
        """
        Fit HMM via VB-EM algorithm with multiple trajectories
        """
        nobss = len(obss) # number of trajectories
        nobs = [len(obs) for obs in obss] # numbers of observations in all trajs
        i_max_obs = np.argmax(nobs)
        obs_flatten = np.vstack(obss) # flattened observations (sum(nobs)xdim)
        nmix = self._nstates
    
        # get posistion id for each traj
        # i.e. obss[i] = obs[pos_ids[i][0]:pos_ids[i][1]]
        pos_ids = [] 
        j = 0
        for i in xrange(nobss):
            pos_ids.append((j,j+nobs[i]))
            j += nobs[i]
    
        if init:
            self._initialize_HMM(obs_flatten)
            old_F = 1.0e20   
    
        # allocate space for forward-backward
        lneta = []
        lngamma = []
        for nn in xrange(nobss):
            lneta.append(np.zeros((len(obss[nn])-1,nmix,nmix)))
            lngamma.append(np.zeros((len(obss[nn]),nmix)))
        lnalpha, lnbeta, lneta_temp = self._allocate_temp(obss[i_max_obs])
    
        for i in xrange(niter):
            lnP = 0.0
            lnf = self._log_like_f(obs_flatten)
            for nn in xrange(nobss):
                Ti,Tf = pos_ids[nn]
                e, g, p = self._E_step(lnf[Ti:Tf],lnalpha[:nobs[nn]],\
                    lnbeta[:nobs[nn]],lneta_temp[:nobs[nn]-1],use_ext)
                lneta[nn] = e[:]
                lngamma[nn] = g[:]
                lnP += p
    
            KL = self._KL_div()
            #print -lnP,KL
            F = -lnP + KL
            dF = F - old_F
            if(abs(dF) < eps):
                print "%8dth iter, Free Energy = %12.6e, dF = %12.6e" %(i,F,dF)
                print "%12.6e < %12.6e Converged" %(dF, eps)
                break

            if i % ifreq == 0 and dF < 0.0:
                print "%6dth iter, F = %15.8e  df = %15.8e"%(i,F,dF)
            elif dF >= 0.0:
                print "%6dth iter, F = %15.8e  df = %15.8e warning"%(i,F,dF)

            old_F = F
            self._M_step(obs_flatten,np.vstack(lneta),lngamma,multi=True)
    
        return self

    def _KL_div(self):
        """
        Compute KL divergence of initial and transition probabilities
        """
        nmix = self._nstates
        KLPi = KL_Dirichlet(self._WPi,self._uPi)
        KLA = 0
        for k in xrange(nmix):
            KLA += KL_Dirichlet(self._WA[k],self._uA[k])
        return KLPi + KLA

    def _calculate_sufficient_statistics(self,obs,lneta,lngamma,multi=False):
        if multi:
            self.z = np.exp(np.vstack(lngamma))
            self.z0 = np.exp([lg[0] for lg in lngamma]).sum(0)
        else:
            # z[n,k] = Q(Zn=k)
            self.z = np.exp(lngamma)

    def _update_parameters(self,obs,lneta,lngamma,multi=False):
        if multi :
            self._WPi = self._uPi + self.z0
        else:
            #self.WPi = self._uPi + self.z.sum(0)
            # update parameters of initial prob 
            self._WPi = self._uPi + self.z[0]

        # update parameters of transition prob 
        self._WA = self._uA + np.exp(lneta).sum(0)
        for k in xrange(self._nstates):
            self._lnA[k,:] = digamma(self._WA[k,:]) \
                    - digamma(self._WA[k,:].sum())

        # recalculate expetations
        self._lnpi = digamma(self._WPi) - digamma(self._WPi.sum())
        self._epi = self._WPi / self._WPi.sum()
        self._eA = self._WA / self._WA.sum(1)[:,np.newaxis]
        
    def getExpectations(self):
        """
        Calculate expectations of parameters over posterior distribution
        """
        self.A = self._WA / self._WA.sum(1)[:,np.newaxis]
        # <pi_k>_Q(pi_k)
        ##self.pi = E_pi_Dirichlet(self._u)
        ev = eig(model.A.T)
        self.pi = abs(ev[1][:,ev[0].argmax()])
        
        return self.pi, self.A

    def getRelaventCluster(self,eps=1.0e-2):
        """
        return parameters of relavent clusters
        """
        self.getExpectations()
        nmix = self._nstates
        ids = []
        sorted_ids = (-self.pi).argsort()
        for k in sorted_ids:
            if self.pi[k] > eps:
                ids.append(k)
        pi = self.pi[ids]
        A = np.array([AA[ids] for AA in self.A[ids]])
        return ids,pi,A
        
class VBMultinomialHMM(_BaseVBHMM):
    def __init__(self,N,M,uPi0=0.5,uA0=0.5,uB0=0.5):
        _BaseVBHMM.__init__(self,N,uPi0,uA0)
        self._mstates = M
        self._uB = np.ones((N,M)) * uB0
        self._WB = np.array(self._uB)
        self._lnB = np.log(dirichlet([1.0]*M,N))
      
    def _log_like_f(self,obs):
        return self._lnB[:,obs].T

    def simulate(self,T):
        pass

    def _update_parameters(self,obs,lneta,lngamma):
        _BaseVBHMM._update_parameters(self,obs,lneta,lngamma)
        for j in xrange(self._mstates):
            self._WB[:,j] = self._uB[:,j] + self.z[obs==j,:].sum(0)
            self._lnB[:,j] = digamma(self._WB[:,j]) \
                    - digamma(self._WB[:,j].sum())

class VBGaussianHMM(_BaseVBHMM):
    """
    VB-HMM with Gaussian emission probability.
    VB-E step is Forward-Backward Algorithm.
    Parameter estimation is almost same as VBGMM.
    """
    def __init__(self,N,uPi0=0.5,uA0=0.5,m0=0.0,beta0=1,nu0=1,s0=0.01):
        _BaseVBHMM.__init__(self,N,uPi0,uA0)
        self._m0 = m0
        self._beta0 = beta0
        self._nu0 = nu0
        self._s0 = s0
        
    def _initialize_HMM(self,obs,params="ms",scale=10.0):
        _BaseHMM._initialize_HMM(self,obs)
        nmix = self._nstates
        T,D = obs.shape
        if self._nu0 < D:
            self._nu0 += D
        if "m" in params:
            self._m0 = np.mean(obs,0)
        if "s" in params:
            self._V0 = np.cov(obs.T) * scale

        #posterior for hidden states
        self.z = dirichlet(np.tile(1.0/nmix,nmix),T)
        # for mean vector
        self._m, temp = vq.kmeans2(obs,nmix)
        self._beta = np.tile(self._beta0,nmix)
        # for covarience matrix
        self._V = np.tile(np.array(self._V0),(nmix,1,1))
        self._nu = self.nu = np.tile(float(T)/nmix,nmix)

        # aux
        self._C = np.array(self._V)
    
    def getExpectations(self):
        """
        Calculate expectations of parameters over posterior distribution
        """
        # <pi_k>_Q(pi_k)
        ##self.pi = E_pi_Dirichlet(self._u)
        ev = eig(model._eA.T)
        self.pi = abs(ev[1][:,ev[0].argmax()])

        # <mu_k>_Q(mu_k,W_k)
        self.mu = np.array(self._m)

        # inv(<W_k>_Q(W_k))
        self.cv = self._V / self._nu[:,np.newaxis,np.newaxis]

        return self.pi, self.mu, self.cv    
    
    def _log_like_f(self,obs):
        return log_like_Gauss2(obs,self._nu,self._V,self._beta,self._m)
    
    def _calculate_sufficient_statistics(self,obs,lneta,lngamma,multi=False):
        nmix = self._nstates
        T,D = obs.shape
        _BaseVBHMM._calculate_sufficient_statistics(\
                self,obs,lneta,lngamma,multi)
        self._N = self.z.sum(0)
        self._xbar = np.dot(self.z.T,obs) / self._N[:,np.newaxis]
        for k in xrange(nmix):
            dobs = obs - self._xbar[k]
            self._C[k] = np.dot((self.z[:,k]*dobs.T),dobs)
        

    def _update_parameters(self,obs,lneta,lngamma,multi=False):
        nmix = self._nstates
        T,D = obs.shape
        _BaseVBHMM._update_parameters(self,obs,lneta,lngamma,multi)
        self._beta = self._beta0 + self._N
        self._nu = self._nu0 + self._N
        self._V = self._V0 + self._C
        for k in xrange(nmix):
            self._m[k] = (self._beta0 * self._m0 + self._N[k] * self._xbar[k])\
                        / self._beta[k]
            dx = self._xbar[k] - self._m0
            self._V[k] += (self._beta0 * self._N[k] / self._beta[k]) \
                * np.outer(dx, dx)
                
    def _KL_div(self):
        nmix = self._nstates
        KL = _BaseVBHMM._KL_div(self)
        for k in xrange(nmix):
            KLg = KL_GaussWishart(self._nu[k],self._V[k],self._beta[k],\
                self._m[k],self._nu0,self._V0,self._beta0,self._m0)
            KL += KLg
        return KL

    def getRelaventCluster(self,eps=1.0e-2):
        ids,pi,A = _BaseVBHMM.getRelaventCluster(self,eps)
        self.getExpectations()
        m = self.mu[ids]
        cv = self.cv[ids]
        return ids,pi,A,m,cv

    def getClustPos(self,obs,eps=1.0e-2):
        ids,pi,A,m,cv = self.getRelaventCluster(eps)
        codes = self.decode(obs)
        clust_pos = []
        for k in ids:
            clust_pos.append(codes==k)
        return clust_pos

    #def compareCluster(self,i,j):
    #    KL1 = KL_GaussWishart(self.nu[i],self.s[i],self.beta[i],self._m[i],\
    #                          self.nu[j],self.s[j],self.beta[j],self._m[j])
    #    KL2 = KL_GaussWishart(self.nu[j],self.s[j],self.beta[j],self._m[j],\
    #                          self.nu[i],self.s[i],self.beta[i],self.m[i])
    #    return 0.5 * (KL1 + KL2)

    def mergeCluster(self,i,j,obs,copy=False,update=True):
        if copy:
          old_z = np.array(self.z)
    
        self.z[:,i] += self.z[:,j]
        self.z[:,j] = 1.0e-15
        
        if update: 
            self._M_step(obs)
            self._E_step(obs)
        if copy:
            return old_z

    def plot1d(self,obs,d1=0,eps=0.01,clust_pos=None):
        symbs = ".hd^x+"
        l = np.arange(len(obs))
        if clust_pos == None:
            clust_pos = self.getClustPos(obs,eps)
        try :
            import matplotlib.pyplot as plt
        except ImportError :
            print "cannot import pyplot"
            return
        for k,pos in enumerate(clust_pos):
            symb = symbs[k / 6]
            plt.plot(l[pos],obs[pos,d1],symb,label="%3dth cluster"%k)
        plt.legend(loc=0)
        plt.show()

    def plot2d(self,obs,d1=0,d2=1,eps=0.01,clust_pos=None):
        symbs = ".hd^x+"
        if clust_pos == None:
            clust_pos = self.getClustPos(obs,eps)
        try :
            import matplotlib.pyplot as plt
        except ImportError :
            print "cannot import pyplot"
            return
        for k,pos in enumerate(clust_pos):
            symb = symbs[k / 6]
            plt.plot(obs[pos,d1],obs[pos,d2],symb,label="%3dth cluster"%k)
        plt.legend(loc=0)
        plt.show()
      
if __name__ == "__main__":
    from sys import argv
    from scipy.linalg import eig
    ifreq = 10
    imax = 10000
    #Y = testData(5000)
    os = []
    zs = []
    for i in range(int(argv[2])):
        z,o = test_model.simulate(50)
        os.append(o)
        zs.append(z)
    o2 = np.vstack(os)
    model = VBGaussianHMM(int(argv[1]))
    if "-mult" in argv :
        model.fit_multi(os,imax,ifreq=ifreq)
    else:
        model.fit(o2,imax,ifreq=ifreq)
    model.plot2d(o2)
